"""Terminal images as Sixel, for Windows Terminal (issue #777): the encoder,
detecting a terminal that draws Sixel, and opening the chart when no
terminal protocol works. Free of the CLI's fixtures, so the Windows job runs
it against the installed program."""

from __future__ import annotations

import io
import re

import numpy as np
import pytest
from PIL import Image

from zabob.retirement import oscompat
from zabob.retirement.sim import chain_graph


def _decode(sequence: str) -> tuple[np.ndarray, dict[int, tuple[int, int, int]]]:
    """The pixels (palette indexes, -1 where nothing was drawn) and the
    palette (percents) of a Sixel image, read back as a terminal would."""
    body = sequence.removesuffix("\n")
    assert body.startswith("\x1bPq") and body.endswith("\x1b\\")
    body = body[3:-2]
    raster = re.match(r'"1;1;(\d+);(\d+)', body)
    assert raster is not None
    width, height = int(raster.group(1)), int(raster.group(2))
    body = body[raster.end():]
    pixels = np.full((height + 6, width), -1, dtype=np.int16)
    palette: dict[int, tuple[int, int, int]] = {}
    x = top = 0
    color = 0
    for token in re.finditer(r"#(\d+);2;(\d+);(\d+);(\d+)|#(\d+)|!(\d+)(.)|([?-~])|(\$)|(-)", body):
        define, red, green, blue, select, count, repeated, char, cr, nl = token.groups()
        if define is not None:
            palette[int(define)] = (int(red), int(green), int(blue))
        elif select is not None:
            color = int(select)
        elif cr:
            x = 0
        elif nl:
            x, top = 0, top + 6
        else:
            n, char = (int(count), repeated) if count else (1, char)
            bits = ord(char) - 63
            for row in range(6):
                if bits & (1 << row):
                    pixels[top + row, x:x + n] = color
            x += n
    assert top + 6 >= height
    return pixels[:height], palette


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_sixel_round_trips_a_small_image() -> None:
    # Bands of six rows, and a seventh row that leaves the last band short.
    rgb = np.zeros((7, 9, 3), dtype=np.uint8)
    rgb[:, :] = (255, 255, 255)
    rgb[2, :] = (255, 0, 0)  # a red line across
    rgb[:, 4] = (0, 0, 255)  # a blue line down, over it
    rgb[6, 7:] = (0, 128, 0)
    sequence = chain_graph.sixel_sequence(_png(Image.fromarray(rgb)))
    pixels, palette = _decode(sequence)
    assert pixels.shape == (7, 9) and (pixels >= 0).all()  # every pixel drawn, none past the edge
    drawn = np.array([[palette[i] for i in row] for row in pixels])
    expected = np.round(rgb.astype(int) * 100 / 255)
    assert (drawn == expected).all()


def test_sixel_runs_compress_a_flat_fill() -> None:
    sequence = chain_graph.sixel_sequence(_png(Image.new("RGB", (300, 12), "white")))
    # One color, two bands, each a single run: no 300 characters per band.
    assert sequence.count("!300~") == 2 and len(sequence) < 80


def test_sixel_draws_transparency_on_white() -> None:
    clear = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    pixels, palette = _decode(chain_graph.sixel_sequence(_png(clear)))
    assert {palette[i] for i in pixels.flat} == {(100, 100, 100)}


def test_sixel_shrinks_an_image_to_the_columns_it_may_fill() -> None:
    wide = Image.new("RGB", (1000, 60), "white")
    pixels, _ = _decode(chain_graph.sixel_sequence(_png(wide), columns=50, cell=(10.0, 20.0)))
    assert pixels.shape == (30, 500)  # 50 columns of 10 pixels, the shape kept
    narrow, _ = _decode(chain_graph.sixel_sequence(_png(wide), columns=200, cell=(10.0, 20.0)))
    assert narrow.shape == (60, 1000)  # fits: never grown


def test_sixel_keeps_to_256_colors() -> None:
    rng = np.random.default_rng(0)
    noise = rng.integers(0, 256, size=(40, 40, 3), dtype=np.uint8)
    pixels, palette = _decode(chain_graph.sixel_sequence(_png(Image.fromarray(noise))))
    assert len(palette) <= 256 and set(np.unique(pixels).tolist()) <= set(palette)


@pytest.mark.parametrize(("reply", "sixel"), [
    (b"\x1b[?61;4;6;7;14;21;22;23;24;28;32;42c", True),  # Windows Terminal 1.22
    (b"\x1b[?62;22c", False),
    (b"\x1b[?4;22c", False),  # 4 as the terminal's class is no attribute
    (b"\x1b[?1;0c", False),  # the console answering for an older terminal
    (b"", False),
])
def test_sixel_reply(reply: bytes, sixel: bool) -> None:
    assert chain_graph.sixel_reply(reply) is sixel


@pytest.fixture
def at_a_terminal(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    for name in ("TMUX", "ANALYSIS_IMAGE_PROTOCOL", "TERM_PROGRAM", "WT_SESSION", "SSH_CONNECTION", "SSH_TTY"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


@pytest.mark.parametrize(("reply", "env", "expected"), [
    (b"\x1b[?61;4;6;7;22c", {}, "sixel"),  # foot, xterm -ti vt340, Windows Terminal
    (b"\x1b[?62;4;22c", {"TERM_PROGRAM": "vscode"}, "iterm"),  # a PNG over 256 colors
    (b"\x1b_Gi=31;OK\x1b\\\x1b[?62;4;22c", {}, "kitty"),
    (b"\x1b[?1;0c", {"WT_SESSION": "4c1d"}, "sixel"),  # the console answered for Windows Terminal
    (b"\x1b[?62;22c", {}, None),
])
def test_terminal_protocol_finds_sixel(
    at_a_terminal: pytest.MonkeyPatch, reply: bytes, env: dict[str, str], expected: str | None,
) -> None:
    for name, value in env.items():
        at_a_terminal.setenv(name, value)
    at_a_terminal.setattr(chain_graph, "_ask_terminal", lambda query: reply)
    assert chain_graph.terminal_protocol() == expected


def test_windows_terminal_gets_sixel_when_the_console_cant_be_asked(at_a_terminal: pytest.MonkeyPatch) -> None:
    def no_console(query: str) -> bytes:
        raise OSError("the input isn't a console")

    at_a_terminal.setattr(chain_graph, "_ask_terminal", no_console)
    assert chain_graph.terminal_protocol() is None
    at_a_terminal.setenv("WT_SESSION", "4c1d")
    assert chain_graph.terminal_protocol() == "sixel"


@pytest.mark.parametrize(("forced", "expected"), [("sixel", "sixel"), ("file", None), ("open", None)])
def test_sixel_and_the_fallbacks_can_be_forced(
    at_a_terminal: pytest.MonkeyPatch, forced: str, expected: str | None,
) -> None:
    at_a_terminal.setenv("ANALYSIS_IMAGE_PROTOCOL", forced)
    at_a_terminal.setattr(chain_graph, "_ask_terminal", lambda query: b"\x1b_Gi=31;OK\x1b\\")
    assert chain_graph.terminal_protocol() == expected


def test_cell_size_asks_the_terminal_when_the_ioctl_cant_say(at_a_terminal: pytest.MonkeyPatch) -> None:
    pytest.importorskip("fcntl")  # Windows has no ioctl, and asks without it anyway
    at_a_terminal.setattr("fcntl.ioctl", lambda *args: b"\0" * 8)  # rows and columns, no pixels
    at_a_terminal.setattr(chain_graph, "_ask_terminal", lambda query: b"\x1b[6;20;10t\x1b[?61;4c")
    assert chain_graph.cell_size() == (10.0, 20.0)
    at_a_terminal.setattr(chain_graph, "_ask_terminal", lambda query: b"\x1b[?61;4c")
    assert chain_graph.cell_size() is None


@pytest.mark.parametrize(("env", "tty", "expected"), [
    ({}, True, True),
    ({}, False, False),  # a pipe: nobody is watching
    ({"SSH_CONNECTION": "10.0.0.2 50000 10.0.0.1 22"}, True, False),  # the viewer would open elsewhere
    ({"SSH_CONNECTION": "10.0.0.2 50000 10.0.0.1 22", "ANALYSIS_IMAGE_PROTOCOL": "open"}, True, True),
    ({"ANALYSIS_IMAGE_PROTOCOL": "file"}, True, False),
    ({"ANALYSIS_IMAGE_PROTOCOL": "none"}, True, False),
])
def test_open_fallback(
    at_a_terminal: pytest.MonkeyPatch, env: dict[str, str], tty: bool, expected: bool,
) -> None:
    at_a_terminal.setattr("sys.stdout.isatty", lambda: tty)
    at_a_terminal.setenv("DISPLAY", ":0")  # a Linux desktop
    for name, value in env.items():
        at_a_terminal.setenv(name, value)
    assert chain_graph.open_fallback() is expected


def test_open_fallback_needs_a_desktop_on_linux(at_a_terminal: pytest.MonkeyPatch) -> None:
    at_a_terminal.setattr("sys.platform", "linux")
    at_a_terminal.delenv("DISPLAY", raising=False)
    at_a_terminal.delenv("WAYLAND_DISPLAY", raising=False)
    assert chain_graph.open_fallback() is False


@pytest.mark.skipif(oscompat.WINDOWS, reason="a console's answer depends on where the tests run")
def test_enable_vt_output_off_windows() -> None:
    assert oscompat.enable_vt_output() is True
