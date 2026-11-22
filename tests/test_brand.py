"""Every doc page's banner is its own, titled from its heading and colored
by its part of the docs (#661). The SVGs themselves depend on the installed
Inter fonts, so this checks what each says, not its every byte; the
banners are made by docs/assets/brand/src/brand.py."""

from __future__ import annotations

import importlib.util
import os
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest


@pytest.fixture(scope="module")
def brand(repo_root: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("brand", repo_root / "docs" / "assets" / "brand" / "src" / "brand.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Its dataclasses look their module up while it runs.
    sys.modules["brand"] = module
    spec.loader.exec_module(module)
    return module


def test_every_banner_line_names_the_page_s_own_banner(brand: ModuleType, repo_root: Path) -> None:
    pages = list(brand.pages())
    assert len(pages) > 30  # the docs, the notebooks' README, ...
    wrong = []
    for page in pages:
        svg = brand.BRAND / "banners" / brand.banner_name(page)
        title = brand.title_of(page)
        line = f"![{title.replace('[', '').replace(']', '')}]({Path(os.path.relpath(svg, page.parent)).as_posix()})"
        head = page.read_text(encoding="utf-8").split("\n", 1)[0]
        text = svg.read_text(encoding="utf-8") if svg.exists() else ""
        label = re.search(r'aria-label="([^"]*)"', text)
        if head != line or label is None or label[1].replace("&quot;", '"').replace("&amp;", "&") != title \
                or brand.section_of(page).color not in text:
            wrong.append(str(page.relative_to(repo_root)))
    assert wrong == [], "run: .venv/bin/python docs/assets/brand/src/brand.py banners"


def test_no_banner_is_left_without_its_page(brand: ModuleType) -> None:
    named = {brand.banner_name(page) for page in brand.pages()}
    assert {svg.name for svg in (brand.BRAND / "banners").glob("*.svg")} == named


def test_pages_get_their_part_of_the_docs(brand: ModuleType, repo_root: Path) -> None:
    labels = {path: brand.section_of(repo_root / path).label for path in (
        "docs/architecture/README.md", "docs/guides/chains.md", "docs/videos/README.md",
        "docs/user-guide.md", "notebooks/README.md")}
    assert list(labels.values()) == ["ARCHITECTURE", "GUIDE", "VIDEOS", "USER GUIDE", "USER GUIDE"]
