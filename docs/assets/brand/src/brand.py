"""Make the logo, the favicons and every doc page's banner (#661).

From the repository's top, with the repository's Python:

    .venv/bin/python docs/assets/brand/src/brand.py           # everything
    .venv/bin/python docs/assets/brand/src/brand.py banners   # only the banners

The text in every SVG is outlined (turned into paths) from the Inter fonts,
since GitHub shows a markdown image without web fonts. The fonts come from
the system (fc-match): the video image and most Linux desktops have them
(`fonts-inter`); macOS gets them from https://rsms.me/inter/.

Banners: every markdown page that opens with a banner line
(``![...](<path>/assets/brand/banners/<name>.svg)``, or the old shared
``banner.jpg``) gets its own banner, titled with the page's first heading
and colored by the part of the docs it is in (``SECTIONS``); the line is
rewritten to point at it. A new page gets one by starting with any banner
line and running this. ``tests/test_brand.py`` checks every banner is the
one this would make.
"""

from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from xml.sax.saxutils import escape

from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

SRC = Path(__file__).resolve().parent
BRAND = SRC.parent
REPO = BRAND.parents[2]

# docs/videos/theme/theme.toml's palette.
BG = "#10242f"
SURFACE = "#1b3a48"
INK = "#f4efe6"
MUTED = "#a9bcc4"
GOLD = "#f2a541"
TEAL = "#4fb3a9"
TERRACOTTA = "#e07a5f"
SLATE = "#8aa6d6"


# -- outlined text ----------------------------------------------------------------


@cache
def _font(name: str) -> TTFont:
    path = subprocess.run(["fc-match", "-f", "%{file}", name], capture_output=True, text=True,
                          check=True).stdout.strip()
    if Path(path).stem.replace("-", "").lower() != name.replace(" ", "").replace(":style=", "").lower():
        sys.exit(f"brand.py: font {name!r} isn't installed (fc-match gave {path})")
    return TTFont(path)


def text_width(text: str, font: str, size: float, tracking: float = 0) -> float:
    f = _font(font)
    cmap, hmtx, upm = f.getBestCmap(), f["hmtx"], f["head"].unitsPerEm
    advance = sum(hmtx[cmap.get(ord(c), cmap[ord("?")])][0] for c in text)
    return advance * size / upm + tracking * max(len(text) - 1, 0)


def _number(value: float) -> str:
    """A coordinate to a tenth of a pixel: finer is invisible, and only bloats the file."""
    return f"{value:.1f}".rstrip("0").rstrip(".")


def text_path(text: str, font: str, size: float, x: float, y: float, tracking: float = 0) -> str:
    """The SVG path data of ``text`` set in ``font`` at ``size`` px, its
    baseline starting at (x, y). ``tracking`` adds px between letters."""
    f = _font(font)
    cmap, glyphs, hmtx = f.getBestCmap(), f.getGlyphSet(), f["hmtx"]
    scale = size / f["head"].unitsPerEm
    pen = SVGPathPen(glyphs, ntos=_number)
    for c in text:
        name = cmap.get(ord(c), cmap[ord("?")])
        glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, x, y)))
        x += hmtx[name][0] * scale + tracking
    return pen.getCommands()


def cap_height(font: str, size: float) -> float:
    f = _font(font)
    pen = BoundsPen(f.getGlyphSet())
    f.getGlyphSet()["H"].draw(pen)
    assert pen.bounds is not None
    return pen.bounds[3] * size / f["head"].unitsPerEm


HEADING = "Inter Display:style=Bold"
LABEL = "Inter:style=SemiBold"


# -- the logo: a fan of futures ---------------------------------------------------

# One start, a widening range of outcomes, the median in gold: the
# simulator's ensembles in one mark. Drawn on a 512 grid.
ORIGIN = (92, 318)
ENDS = [(436, 96), (436, 156), (436, 214), (436, 268), (436, 322), (436, 380), (436, 434)]
MEDIAN = 2  # the gold one, a little above level: a plan that holds


def _curve(end: tuple[float, float]) -> str:
    (x0, y0), (x1, y1) = ORIGIN, end
    # Every path leaves the start heading the same way, then spreads: the
    # future is nearly known at first and ever less so.
    return f"M{x0} {y0} C{x0 + 120} {y0 - 28} {x1 - 150} {y1} {x1} {y1}"


def fan(*, detail: bool = True, ink: str = INK) -> str:
    """The mark's paths (no background). ``detail`` False keeps only the
    range and the median, for favicon sizes."""
    lo, hi = ENDS[0], ENDS[-1]
    band = (f'<path d="M{ORIGIN[0]} {ORIGIN[1]} C{ORIGIN[0] + 120} {ORIGIN[1] - 28} {lo[0] - 150} {lo[1]} '
            f'{lo[0]} {lo[1]} L{hi[0]} {hi[1]} C{hi[0] - 150} {hi[1]} {ORIGIN[0] + 120} {ORIGIN[1] - 28} '
            f'{ORIGIN[0]} {ORIGIN[1]}Z" fill="{TEAL}" fill-opacity="{0.22 if detail else 0.5}"/>')
    lines = []
    if detail:
        for i, end in enumerate(ENDS):
            if i != MEDIAN:
                lines.append(f'<path d="{_curve(end)}" fill="none" stroke="{ink}" stroke-opacity="0.55" '
                             f'stroke-width="14" stroke-linecap="round"/>')
    width = 30 if detail else 60
    lines.append(f'<path d="{_curve(ENDS[MEDIAN])}" fill="none" stroke="{GOLD}" stroke-width="{width}" '
                 'stroke-linecap="round"/>')
    dot = f'<circle cx="{ORIGIN[0]}" cy="{ORIGIN[1]}" r="{34 if detail else 60}" fill="{GOLD}"/>'
    return band + "".join(lines) + dot


def icon_svg(*, detail: bool = True, size: int | None = None) -> str:
    wh = f' width="{size}" height="{size}"' if size else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"{wh}>'
            f'<rect width="512" height="512" rx="112" fill="{BG}"/>{fan(detail=detail)}</svg>\n')


def lockup_svg(*, dark: bool) -> str:
    """The mark and the name side by side; ``dark`` for a dark page (light
    text, no tile), else on a light page."""
    ink, sub = (INK, MUTED) if dark else (BG, "#4a6470")
    size, h = 112, 256
    x = 256 + 40
    words = text_path("Zabob Retirement", HEADING, size, x, 128 + cap_height(HEADING, size) / 2 - 18)
    tag = text_path("A simulator for your future", LABEL, 36, x + 4, 128 + cap_height(HEADING, size) / 2 + 46)
    width = x + max(text_width("Zabob Retirement", HEADING, size), text_width("A simulator for your future",
                                                                               LABEL, 36) + 4) + 24
    mark = (f'<g transform="scale(0.5)"><rect width="512" height="512" rx="112" fill="{BG}"/>'
            f'{fan()}</g>')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {h}">{mark}'
            f'<path d="{words}" fill="{ink}"/><path d="{tag}" fill="{sub}"/></svg>\n')


# -- banners ----------------------------------------------------------------------

@dataclass(frozen=True)
class Section:
    label: str
    color: str


# The part of the docs a page is in, by its path under docs/ (first match);
# a page elsewhere (notebooks/, historical_data/) is in the user guide's.
SECTIONS: list[tuple[str, Section]] = [
    ("architecture/", Section("ARCHITECTURE", SLATE)),
    ("guides/", Section("GUIDE", TEAL)),
    ("videos/", Section("VIDEOS", TERRACOTTA)),
    ("", Section("USER GUIDE", GOLD)),
]

BANNER_W, BANNER_H = 1280, 186
TITLE_BOX = (430, 1232)  # the title's left and right limits, clear of Zabob
BANNER_LINE = re.compile(r"^!\[[^\]]*\]\((?P<path>[^)]*assets/brand/(?:banner\.jpg|banners/[\w.-]+\.svg))\)$")


def section_of(page: Path) -> Section:
    rel = page.relative_to(REPO).as_posix()
    inside = rel.removeprefix("docs/") if rel.startswith("docs/") else ""
    return next(s for prefix, s in SECTIONS if inside.startswith(prefix))


def _lines(title: str, room: float) -> tuple[list[str], float]:
    """``title`` set to fit ``room`` px: one line from 46 px down to 34,
    else two lines from 38 px down to 26."""
    for size in range(46, 33, -1):
        if text_width(title, HEADING, size) <= room:
            return [title], size
    words = title.split()
    for size in range(38, 25, -1):
        for cut in range(len(words) - 1, 0, -1):
            first, second = " ".join(words[:cut]), " ".join(words[cut:])
            if text_width(first, HEADING, size) <= room and text_width(second, HEADING, size) <= room:
                return [first, second], size
    return [title], 26


@cache
def _background() -> str:
    # banner.jpg, saved smaller (Pillow, quality 70): it is shown under the
    # shade, in every banner, and each SVG carries its own copy.
    return base64.b64encode((SRC / "banner-background.jpg").read_bytes()).decode()


def banner_svg(title: str, section: Section) -> str:
    left, right = TITLE_BOX
    lines, size = _lines(title, right - left)
    label_size = 15
    cap = cap_height(HEADING, size)
    gap = size * 0.3
    block = cap * len(lines) + gap * (len(lines) - 1)
    label_gap = 16
    top = (BANNER_H - (cap_height(LABEL, label_size) + label_gap + block)) / 2
    label_y = top + cap_height(LABEL, label_size)
    label_w = text_width(section.label, LABEL, label_size, tracking=2.4)
    paths = [f'<path d="{text_path(section.label, LABEL, label_size, right - label_w, label_y, 2.4)}" '
             f'fill="{section.color}"/>']
    y = label_y + label_gap + cap
    for line in lines:
        w = text_width(line, HEADING, size)
        paths.append(f'<path d="{text_path(line, HEADING, size, right - w, y)}" fill="{INK}"/>')
        y += cap + gap
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {BANNER_W} {BANNER_H}" '
        f'role="img" aria-label="{escape(title, {chr(34): "&quot;"})}">'
        "<defs>"
        '<linearGradient id="shade" x1="0" x2="1">'
        f'<stop offset="0.22" stop-color="{BG}" stop-opacity="0"/>'
        f'<stop offset="0.48" stop-color="{BG}" stop-opacity="0.72"/>'
        f'<stop offset="1" stop-color="{BG}" stop-opacity="0.86"/></linearGradient>'
        "</defs>"
        f'<image width="{BANNER_W}" height="{BANNER_H}" href="data:image/jpeg;base64,{_background()}"/>'
        f'<rect width="{BANNER_W}" height="{BANNER_H}" fill="url(#shade)"/>'
        f'<rect y="{BANNER_H - 6}" width="{BANNER_W}" height="6" fill="{section.color}"/>'
        + "".join(paths) + "</svg>\n")


def pages() -> Iterator[Path]:
    """The markdown pages that open with a banner line."""
    for page in sorted(REPO.glob("**/*.md")):
        rel = page.relative_to(REPO).parts
        if rel[0] in {"node_modules", "data", "out", "state", ".venv"} or "node_modules" in rel:
            continue
        first = page.read_text(encoding="utf-8").split("\n", 1)[0]
        if BANNER_LINE.match(first):
            yield page


def title_of(page: Path) -> str:
    for line in page.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            return re.sub(r"[`*_]", "", line[2:]).strip()
    return page.stem.replace("-", " ").title()


def banner_name(page: Path) -> str:
    rel = page.relative_to(REPO).with_suffix("").as_posix()
    return re.sub(r"[^\w.-]+", "-", rel.removeprefix("docs/")).lower() + ".svg"


def expected(page: Path) -> tuple[Path, str, str]:
    """The banner file a page should have, its SVG, and the page's banner
    line."""
    title = title_of(page)
    svg = BRAND / "banners" / banner_name(page)
    rel = Path(os.path.relpath(svg, page.parent)).as_posix()
    alt = title.replace("[", "").replace("]", "")
    return svg, banner_svg(title, section_of(page)), f"![{alt}]({rel})"


def make_banners() -> list[str]:
    done = []
    (BRAND / "banners").mkdir(exist_ok=True)
    wanted = set()
    for page in pages():
        svg, text, line = expected(page)
        wanted.add(svg)
        if not svg.exists() or svg.read_text(encoding="utf-8") != text:
            svg.write_text(text, encoding="utf-8")
            done.append(f"wrote {svg.relative_to(REPO)}")
        head, _, rest = page.read_text(encoding="utf-8").partition("\n")
        if head != line:
            page.write_text(f"{line}\n{rest}", encoding="utf-8")
            done.append(f"pointed {page.relative_to(REPO)} at it")
    for stale in sorted(set((BRAND / "banners").glob("*.svg")) - wanted):
        stale.unlink()
        done.append(f"removed {stale.relative_to(REPO)}")
    return done


# -- files ------------------------------------------------------------------------

FAVICON_PNG = {16: False, 32: False, 48: False, 180: True, 192: True, 512: True}


def _raster(svg: str, size: tuple[int, int], out: Path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        # A cloud container's pre-installed Chromium, when Playwright's own
        # download is missing.
        prebuilt = Path("/opt/pw-browsers/chromium")
        browser = p.chromium.launch(executable_path=str(prebuilt) if prebuilt.exists() else None)
        page = browser.new_page(viewport={"width": size[0], "height": size[1]}, device_scale_factor=1)
        page.set_content(f'<html><body style="margin:0;background:transparent">{svg}</body></html>')
        page.locator("svg").screenshot(path=str(out), omit_background=True)
        browser.close()


def make_logo() -> list[str]:
    logo, favicon = BRAND / "logo", BRAND / "favicon"
    logo.mkdir(exist_ok=True)
    favicon.mkdir(exist_ok=True)
    files = {
        logo / "icon.svg": icon_svg(),
        logo / "lockup-dark.svg": lockup_svg(dark=True),
        logo / "lockup-light.svg": lockup_svg(dark=False),
        favicon / "favicon.svg": icon_svg(detail=False),
    }
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
    for px, detail in FAVICON_PNG.items():
        _raster(icon_svg(detail=detail, size=px), (px, px), favicon / f"icon-{px}.png")
    from PIL import Image

    Image.open(favicon / "icon-48.png").save(
        favicon / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)],
        append_images=[Image.open(favicon / f"icon-{px}.png") for px in (16, 32)])
    for name in ("lockup-dark", "lockup-light"):
        svg = (logo / f"{name}.svg").read_text(encoding="utf-8")
        width = float(re.search(r'viewBox="0 0 ([\d.]+) ', svg)[1])  # type: ignore[index]
        sized = svg.replace("<svg ", f'<svg width="{width * 2:.0f}" height="512" ', 1)
        _raster(sized, (round(width * 2), 512), logo / f"{name}.png")
    return [f"wrote {p.relative_to(REPO)}" for p in sorted([*files, *favicon.glob("*.png"), favicon / "favicon.ico",
                                                           *logo.glob("*.png")])]


if __name__ == "__main__":
    what = sys.argv[1:] or ["logo", "banners"]
    for line in [*(make_logo() if "logo" in what else []), *(make_banners() if "banners" in what else [])]:
        print(line)
