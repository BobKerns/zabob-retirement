"""#123: notebook widgets show their charts as PNGs of plain ``Figure``s
(``notebook_ui.styled.show_figure``), never through pyplot, whose
open-figure list matplotlib-inline's ``flush_figures`` can render from
another thread while a widget is still drawing (#119)."""

# cspell:ignore getcolors maxcolors

from __future__ import annotations

import io
import subprocess
import sys

import pytest
from IPython.display import Image

from zabob.retirement.sim.connection import RunConnection


def test_a_redraw_displays_a_png_with_a_real_chart(two_lot_run: RunConnection,
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """Decode what a redraw actually displays: a blank or corrupted render
    (#119's symptom) still produces PNG bytes, so checking for bytes alone
    would pass."""
    import IPython.display
    from PIL import Image as PILImage

    from zabob.retirement.sim.notebook_ui import accounts_plots

    displayed: list[object] = []
    monkeypatch.setattr(IPython.display, "display", lambda *objs, **_: displayed.extend(objs))
    widget = accounts_plots.account_history_widget(two_lot_run, "asset", "Balances")
    displayed.clear()
    accounts = widget.children[1].account_picker
    # A change of accounts redraws; the first draw has already happened.
    accounts.value = tuple(name for name in accounts.options if name not in accounts.value)[:2]

    images = [shown for shown in displayed if isinstance(shown, Image)]
    assert len(images) == 1
    assert images[0].format == "png"
    assert isinstance(images[0].data, bytes)
    with PILImage.open(io.BytesIO(images[0].data)) as png:
        rgb = png.convert("RGB")
    width, height = rgb.size
    assert width > 300 and height > 200
    colors = rgb.getcolors(maxcolors=width * height) or []
    background = max(colors)[0]
    # Axes, text and a data line: many colors, and a real share of pixels
    # that aren't background. A blank render is one color.
    assert len(colors) > 20
    assert 1 - background / (width * height) > 0.02


def test_the_plotting_helpers_leave_pyplot_unloaded() -> None:
    """``plot_timeseries`` and friends draw on a plain ``Figure`` when given no
    axes: a pyplot figure is one ``flush_figures`` can reach mid-draw."""
    code = ("import sys, pandas as pd\n"
            "from zabob.retirement.sim.plotting import plot_timeseries\n"
            "idx = pd.date_range('2026-01-31', periods=3, freq='ME')\n"
            "plot_timeseries({'x': pd.Series([1.0, 2.0, 3.0], index=idx)}, title='t')\n"
            "print('matplotlib.pyplot' in sys.modules)")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "False"
