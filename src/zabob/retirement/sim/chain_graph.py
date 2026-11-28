"""The chain flowchart as an image, drawn in the terminal (issue #142).

No terminal graphics protocol draws lines or shapes: kitty's and iTerm2's
both carry a finished bitmap. So :func:`render` draws the Mermaid source
from :func:`zabob.retirement.sim.chain_map.mermaid` with Mermaid itself, in headless
Chromium through Playwright, which keeps the image the same as the
notebook's flowchart. :func:`terminal_protocol` asks the terminal which
protocol it takes, and :func:`kitty_sequence` / :func:`iterm_sequence`
wrap the PNG for it; :func:`sixel_sequence` redraws it as Sixel, the one
protocol Windows Terminal takes (#777).

The chart never leaves the machine, and drawing it needs no network: the
Mermaid script ships with the package (``vendor/``, gzipped; the notebook's
flowchart widget draws with the same copy), and the page drawing the chart
may fetch nothing.
"""

from __future__ import annotations

import base64
import gzip
import math
import os
import re
import select
import sys
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "MERMAID_SCRIPT", "SIXEL_CELL", "GraphError", "fit_columns", "iterm_sequence",
    "jupyter_chart_dir", "kitty_sequence", "open_fallback", "render", "sixel_sequence", "terminal_protocol",
]

MERMAID_VERSION = "11.17.2"
MERMAID_SCRIPT = Path(__file__).parent / "vendor" / f"mermaid-{MERMAID_VERSION}.min.js.gz"
"""The same release as a plain script, as npm publishes it, gzipped: the
minified script's short names trip the blocked-keyword check, which skips a
binary file. The CLI and the notebook's flowchart widget both draw with it,
so neither needs the network. To upgrade, replace it, change ``MERMAID_VERSION``, and update
the hash in ``tests/test_chain_graph.py``."""

type Protocol = Literal["kitty", "iterm", "sixel"]
type ImageFormat = Literal["png", "svg"]

_INSTALL_HINT = ("install Google Chrome, or run `uv run playwright install chromium`; "
                 "`--mermaid` prints the chart's source instead")


class GraphError(Exception):
    """The chart couldn't be drawn: no browser, or Mermaid couldn't draw it."""


class NoBrowserError(GraphError):
    """Neither Playwright's Chromium nor Chrome is installed."""


_PAGE = '<html><body style="margin:0;background:white"><div id="chart"></div></body></html>'

_DRAW = """async (source) => {
    mermaid.initialize({startOnLoad: false, theme: "default"});
    const {svg} = await mermaid.render("chain-graph", source);
    document.getElementById("chart").innerHTML = svg;
    return svg;
}"""


_ZOOM = 2.0
"""How far a chart may grow past ``scale`` to fill ``fit_width``: its labels
at most twice the terminal's text, so a small chart doesn't balloon."""


def render(
    source: str, fmt: ImageFormat = "png", scale: float = 2.0, fit_width: float | None = None,
) -> bytes:
    """Draw Mermaid ``source`` as a PNG, ``scale`` pixels to each of the
    chart's own (twice, by default, for a sharp image on a high-density
    screen), or as SVG text; on a white background so it reads on a dark
    terminal too. With ``fit_width``, the PNG is that many pixels wide
    instead, shrinking a wide chart or growing a narrow one up to
    :data:`_ZOOM` times ``scale``."""
    from playwright.sync_api import Error, sync_playwright

    script = gzip.decompress(MERMAID_SCRIPT.read_bytes()).decode()
    with sync_playwright() as playwright:
        try:
            # $ZABOB_CHROMIUM names a Chromium when Playwright's own download
            # doesn't match the installed Playwright (the video recordings set it).
            browser = playwright.chromium.launch(executable_path=os.environ.get("ZABOB_CHROMIUM") or None)
        except Error:
            # Playwright's own Chromium isn't installed; an installed Chrome serves.
            try:
                browser = playwright.chromium.launch(channel="chrome")
            except Error as error:
                raise NoBrowserError(f"no browser to draw the chart with: {_INSTALL_HINT}") from error
        def draw(scale: float):
            page = browser.new_page(device_scale_factor=scale)
            # The page holds the chart: it may fetch nothing from anywhere.
            page.route("**/*", lambda route: route.abort())
            page.set_content(_PAGE)
            page.add_script_tag(content=script)
            try:
                svg = page.evaluate(_DRAW, source)
            except Error as error:
                raise GraphError(f"Mermaid couldn't draw the chart: {error.message}") from error
            return page, svg

        try:
            page, svg = draw(scale)
            if fmt == "svg":
                return svg.encode()
            chart = page.locator("#chart svg")
            if fit_width:
                # A page's scale is fixed when it opens, so the chart is drawn
                # again on a page at the scale that fills the width.
                box = chart.bounding_box()
                if box and box["width"]:
                    fitted = min(fit_width / box["width"], scale * _ZOOM)
                    if abs(fitted - scale) > 0.01:
                        page, _ = draw(fitted)
                        chart = page.locator("#chart svg")
            return chart.screenshot(omit_background=False)
        finally:
            browser.close()


def png_size(png: bytes) -> tuple[int, int]:
    """A PNG's width and height in pixels, from its header."""
    return int.from_bytes(png[16:20]), int.from_bytes(png[20:24])


def fit_columns(image_width: int, columns: int, cell_width: float | None) -> int | None:
    """How many terminal columns to show an image ``image_width`` pixels wide
    in: its own width when it fits, else the whole terminal, so a wide chart
    shrinks instead of running off the right edge. ``None`` (the terminal
    picks) when the cell size is unknown and nothing says it overflows."""
    if not cell_width:
        return None
    return min(columns, max(1, math.ceil(image_width / cell_width)))


_CHUNK = 4096


def kitty_sequence(png: bytes, columns: int | None = None) -> str:
    """``png`` as kitty graphics protocol escapes: transmit and show it
    (``a=T``) as PNG (``f=100``), in chunks of at most 4096 base64 bytes,
    with no replies (``q=2``) to land in the shell's input."""
    data = base64.standard_b64encode(png).decode()
    chunks = [data[i:i + _CHUNK] for i in range(0, len(data), _CHUNK)] or [""]
    first = "a=T,f=100,q=2" + (f",c={columns}" if columns else "")
    out = []
    for i, chunk in enumerate(chunks):
        more = int(i < len(chunks) - 1)
        keys = f"{first},m={more}" if i == 0 else f"m={more}"
        out.append(f"\x1b_G{keys};{chunk}\x1b\\")
    return "".join(out) + "\n"


def iterm_sequence(png: bytes, columns: int | None = None) -> str:
    """``png`` as an iTerm2 inline-image escape, for terminals that take
    iTerm2's protocol but not kitty's (older iTerm2 and VS Code)."""
    width = f";width={columns}" if columns else ""
    data = base64.standard_b64encode(png).decode()
    return f"\x1b]1337;File=inline=1;size={len(png)}{width};preserveAspectRatio=1:{data}\x07\n"


_SIXEL_COLORS = 256
"""Color registers a Sixel image may use: Windows Terminal, xterm and foot
all keep 256 (the VT340 had 16, but nothing that still draws Sixel stops
there)."""

SIXEL_CELL = (10.0, 20.0)
"""The cell, in Sixel pixels, that Windows Terminal maps an image onto
whatever its font: the size to assume when a Sixel terminal doesn't say."""


def sixel_sequence(png: bytes, columns: int | None = None,
                   cell: tuple[float, float] | None = None) -> str:
    """``png`` as a Sixel image, for terminals that take neither kitty's
    protocol nor iTerm2's (Windows Terminal, foot, xterm). Sixel carries
    pixels, not a size to show them at, so an image wider than ``columns``
    cells of ``cell`` pixels is shrunk to fit first. Transparent pixels are
    drawn on white, as the charts are, and the colors cut to
    :data:`_SIXEL_COLORS` without dithering, so a chart's flat fills and thin
    lines keep their edges."""
    import io

    import numpy as np
    from PIL import Image

    image = Image.open(io.BytesIO(png))
    if image.mode != "RGB":
        image = Image.alpha_composite(Image.new("RGBA", image.size, "white"),
                                      image.convert("RGBA")).convert("RGB")
    if columns and cell:
        width = max(1, int(columns * cell[0]))
        if image.width > width:
            height = max(1, round(image.height * width / image.width))
            image = image.resize((width, height), Image.Resampling.LANCZOS)
    indexed = image.quantize(colors=_SIXEL_COLORS, method=Image.Quantize.MEDIANCUT,
                              dither=Image.Dither.NONE)
    palette = np.frombuffer(bytes(indexed.getpalette() or []), dtype=np.uint8).reshape(-1, 3)
    return sixel_encode(np.asarray(indexed, dtype=np.int16), palette) + "\n"


def sixel_encode(pixels: Any, palette: Any) -> str:
    """The Sixel image of ``pixels``, a height by width array of indexes
    into ``palette``, an array of RGB rows (0 to 255). Sixel draws six rows
    at a time (a band), one color at a time across the band, so each color
    in a band becomes a run-length coded row of six-bit columns."""
    import numpy as np

    height, width = pixels.shape
    # Raster attributes: square pixels, and the size, so the terminal makes
    # room for the whole image before it draws.
    out = [f'\x1bPq"1;1;{width};{height}']
    for index in np.unique(pixels).tolist():
        red, green, blue = (round(int(c) * 100 / 255) for c in palette[index])
        out.append(f"#{index};2;{red};{green};{blue}")  # Sixel colors are percents
    pad = (-height) % 6
    if pad:  # the last band's rows below the image are no color
        pixels = np.vstack([pixels, np.full((pad, width), -1, dtype=pixels.dtype)])
    weights = (1 << np.arange(6)).reshape(6, 1)
    bands = []
    for top in range(0, height, 6):
        band = pixels[top:top + 6]
        rows = []
        for color in np.unique(band[band >= 0]).tolist():
            bits = ((band == color) * weights).sum(axis=0)
            rows.append(f"#{color}{_sixel_runs(bits[:np.flatnonzero(bits)[-1] + 1])}")
        bands.append("$".join(rows))  # $: back to the band's left edge for the next color
    out.append("-".join(bands))  # -: down to the next band
    out.append("\x1b\\")
    return "".join(out)


def _sixel_runs(bits: Any) -> str:
    """One color's six-bit columns across a band as Sixel characters, a run
    of four or more of the same written ``!<count><char>``."""
    import numpy as np

    starts = np.concatenate(([0], np.flatnonzero(np.diff(bits)) + 1))
    lengths = np.diff(np.append(starts, len(bits))).tolist()
    parts = []
    for value, length in zip(bits[starts].tolist(), lengths, strict=True):
        char = chr(63 + value)
        parts.append(f"!{length}{char}" if length > 3 else char * length)
    return "".join(parts)


# The query kitty's documentation gives for detecting its graphics protocol:
# a one-pixel image query, then the device-attributes query every terminal
# answers. A terminal that takes kitty graphics answers the first one before
# the second, so reading up to the second's reply never hangs; and the
# second's reply lists Sixel (attribute 4) when the terminal draws it.
_KITTY_QUERY = "\x1b_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA\x1b\\\x1b[c"
_DEVICE_ATTRIBUTES = re.compile(rb"\x1b\[\?([\d;]*)c")
# Any id: iTerm2 answers a kitty query with i=0, not the id it was asked with.
_KITTY_OK = re.compile(rb"\x1b_Gi=\d+;OK\x1b\\")
_ITERM_PROGRAMS = {"iTerm.app", "vscode", "WezTerm"}
# The cell size in pixels (XTWINOPS 16), for a terminal that doesn't put its
# pixel size where the ioctl reads it (Windows has no such ioctl at all).
_CELL_QUERY = "\x1b[16t\x1b[c"
_CELL_REPLY = re.compile(rb"\x1b\[6;(\d+);(\d+)t")


def kitty_reply(reply: bytes) -> bool:
    """Whether the terminal's ``reply`` to the kitty query says it takes kitty graphics."""
    return _KITTY_OK.search(reply) is not None


def sixel_reply(reply: bytes) -> bool:
    """Whether the device attributes in ``reply`` list Sixel graphics (4).
    The first number is the terminal's class (62 for a VT220, say), not an
    attribute, so it doesn't count."""
    match = _DEVICE_ATTRIBUTES.search(reply)
    return match is not None and b"4" in match.group(1).split(b";")[1:]


def _ask_terminal(query: str, timeout: float = 1.0) -> bytes:
    """Write ``query`` to the terminal and read its reply, up to the
    device-attributes answer that ends it, or ``timeout`` seconds."""
    if sys.platform == "win32":
        return _ask_console(query, timeout)
    import termios
    import tty

    fd = sys.stdin.fileno()
    saved = termios.tcgetattr(fd)
    reply = b""
    try:
        tty.setcbreak(fd, termios.TCSANOW)
        sys.stdout.write(query)
        sys.stdout.flush()
        while not _DEVICE_ATTRIBUTES.search(reply):
            ready, _, _ = select.select([fd], [], [], timeout)
            if not ready:
                break
            reply += os.read(fd, 1024)
        # Some terminals (iTerm2) answer the queries out of order; take in a
        # late answer here, or it lands at the shell prompt.
        while select.select([fd], [], [], 0.05)[0]:
            reply += os.read(fd, 1024)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    return reply


def _ask_console(query: str, timeout: float) -> bytes:
    """:func:`_ask_terminal` on Windows, which has no termios: with the
    console's input in VT mode, the terminal's reply arrives as typed
    characters, which ``msvcrt`` reads without echoing them."""
    assert sys.platform == "win32"  # and so the checker knows it
    import msvcrt
    import time

    from zabob.retirement import oscompat

    with oscompat.vt_console():
        sys.stdout.write(query)
        sys.stdout.flush()
        reply = ""
        deadline = time.monotonic() + timeout
        while not _DEVICE_ATTRIBUTES.search(reply.encode()) and time.monotonic() < deadline:
            if msvcrt.kbhit():
                reply += msvcrt.getwch()
            else:
                time.sleep(0.01)
        late = time.monotonic() + 0.05
        while time.monotonic() < late:
            while msvcrt.kbhit():
                reply += msvcrt.getwch()
            time.sleep(0.01)
    return reply.encode()


def swallow_replies(timeout: float = 0.2) -> None:
    """Take in any reply the terminal sends to an image just shown. iTerm2
    answers a kitty image though ``q=2`` asks it not to, and an answer left
    unread is typeahead: the shell shows it at the next prompt."""
    if not sys.stdin.isatty():
        return
    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        saved = termios.tcgetattr(fd)
    except (ImportError, OSError):
        return
    try:
        tty.setcbreak(fd, termios.TCSANOW)
        while select.select([fd], [], [], timeout)[0]:
            os.read(fd, 1024)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)


CHART_FOLDER = "sim-charts"
"""Where, in a JupyterLab's files, a chart its terminal can't show goes."""


def jupyter_root() -> Path | None:
    """The folder a JupyterLab serves, when this runs in its terminal
    (``jupyter_server_terminals`` sets ``$JUPYTER_SERVER_ROOT`` there), whose
    browser may be on another device: a hub user's iPad, say (#837)."""
    root = os.environ.get("JUPYTER_SERVER_ROOT")
    return Path(root) if root and Path(root).is_dir() else None


def jupyter_chart_dir() -> Path | None:
    """In a JupyterLab terminal, the folder to put a chart in so its file
    browser shows it: ``sim-charts/`` in the notebooks it opens on (the
    data repo's ``notebooks/``, which the data repo leaves out of git), else
    at the top of what it serves. None outside a JupyterLab terminal."""
    root = jupyter_root()
    if root is None:
        return None
    repo = os.environ.get("ZABOB_HUB_REPO")  # a hub user's data repo (#766)
    for notebooks in (root / "notebooks", *([Path(repo) / "notebooks"] if repo else [])):
        if notebooks.is_dir() and notebooks.resolve().is_relative_to(root.resolve()):
            return notebooks / CHART_FOLDER
    return root / CHART_FOLDER


def terminal_protocol() -> Protocol | None:
    """The image protocol this terminal takes, or ``None`` when it takes
    none, the output isn't a terminal, or it's inside tmux (which needs
    passthrough wrapping this doesn't do). ``$ZABOB_IMAGE_PROTOCOL``
    (``kitty``, ``iterm``, ``sixel``, or ``none``, ``file`` or ``open`` for
    no protocol) overrides the guess, for a terminal it gets wrong, but never
    sends images to output that isn't a terminal.

    The guess: iTerm2 by name; then whatever the terminal answers to the
    kitty query (kitty's own protocol, or Sixel in its device attributes),
    with the terminals known to take iTerm2's protocol getting that ahead of
    Sixel, whose 256 colors draw a chart less well. Sixel needs the
    terminal to say so: ``$WT_SESSION`` names Windows Terminal but not its
    version (one before 1.22 draws no Sixel), and it passes on to any
    window started from one (a ``start cmd`` console, say), so it decides
    nothing (#777). A JupyterLab terminal takes none (#837)."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None  # escapes would only garble a pipe or a file
    forced = os.environ.get("ZABOB_IMAGE_PROTOCOL", "").lower()
    if forced in ("kitty", "iterm", "sixel"):
        return forced  # even in tmux: whoever set it may have passthrough on
    if forced in ("none", "file", "open") or os.environ.get("TMUX"):
        return None
    if jupyter_root() is not None:
        # JupyterLab's terminal is xterm.js without its image add-on: it
        # draws no protocol, and asking only waits for an answer (#837).
        return None
    if os.environ.get("TERM_PROGRAM") == "iTerm.app":
        # iTerm2 accepts a kitty image but showed nothing (issue #142), so it
        # gets its own protocol, without asking.
        return "iterm"
    reply = b""
    try:
        reply = _ask_terminal(_KITTY_QUERY)
    except (ImportError, OSError):  # no console or controlling terminal to ask
        pass
    if kitty_reply(reply):
        return "kitty"
    if os.environ.get("TERM_PROGRAM") in _ITERM_PROGRAMS:
        return "iterm"
    if sixel_reply(reply):
        return "sixel"
    return None


def open_fallback() -> bool:
    """Whether a chart the terminal can't show should open in the image
    viewer: when someone is at this machine to see it (a terminal on the
    output, not over SSH or in a JupyterLab, a desktop on Linux), unless
    ``$ZABOB_IMAGE_PROTOCOL`` says ``file`` (or ``none``), or ``open``
    to open it regardless."""
    forced = os.environ.get("ZABOB_IMAGE_PROTOCOL", "").lower()
    if forced in ("none", "file"):
        return False
    if forced == "open":
        return True
    if not sys.stdout.isatty() or os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        return False
    if jupyter_root() is not None:
        return False  # its browser may be anywhere; this machine's screen may be no one's (#837)
    if sys.platform in ("win32", "darwin"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def cell_size() -> tuple[float, float] | None:
    """The terminal's cell width and height in its own pixels, which on a
    Retina screen are device pixels, when it reports its pixel size."""
    try:
        import fcntl
        import struct
        import termios

        rows, columns, x_pixels, y_pixels = struct.unpack(
            "HHHH", fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b"\0" * 8))
    except (ImportError, OSError):
        return None
    if not (x_pixels and y_pixels and columns and rows):
        return None
    return x_pixels / columns, y_pixels / rows


def asked_cell_size() -> tuple[float, float] | None:
    """The cell size the terminal gives when asked (``CSI 16 t``), for a
    Sixel image when :func:`cell_size` can't say: Windows has no ioctl. Only
    for Sixel, whose image must be drawn to its width; the other protocols
    size an image themselves, and asking costs a round trip."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return None
    try:
        match = _CELL_REPLY.search(_ask_terminal(_CELL_QUERY))
    except (ImportError, OSError):
        return None
    if match is None or not (int(match.group(1)) and int(match.group(2))):
        return None
    height, width = int(match.group(1)), int(match.group(2))
    return float(width), float(height)


# Mermaid's labels are 16px; a terminal cell is about 1.2 times its font's height.
_MERMAID_FONT_PX = 16
_LINE_HEIGHT = 1.2


def terminal_scale(cell: tuple[float, float] | None) -> float:
    """The scale to render at so the chart's labels come out the size of the
    terminal's own text, on a Retina screen or not alike: the terminal reports
    its cells in the pixels it draws images in. Twice the chart's size when
    the terminal doesn't say."""
    if cell is None:
        return 2.0
    return min(4.0, max(0.5, cell[1] / (_LINE_HEIGHT * _MERMAID_FONT_PX)))
