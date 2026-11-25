"""Smoke tests for zabob.retirement.sim.plotting. Its charts draw on plain
``Figure``s, so no backend is needed."""

from __future__ import annotations

import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle

from zabob.retirement.sim.plotting import (
    include_zero,
    plot_income_expense_net,
    plot_stacked_bar,
    plot_timeseries,
)


def _bars(ax: Axes) -> list[Rectangle]:
    return [patch for patch in ax.patches if isinstance(patch, Rectangle)]


def test_plot_timeseries_returns_axes_with_legend() -> None:
    idx = pd.date_range("2026-01-31", periods=3, freq="ME")
    series = {"nominal": pd.Series([1.0, 2.0, 3.0], index=idx)}

    ax = plot_timeseries(series, title="net worth")

    assert ax.get_title() == "net worth"
    assert ax.get_legend() is not None


def test_plot_stacked_bar_returns_axes() -> None:
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]}, index=pd.Index([2026, 2027], name="year"))

    ax = plot_stacked_bar(df, ["a", "b"], ["#111111", "#222222"], title="stacked")

    assert ax.get_title() == "stacked"
    assert [t.get_text() for t in ax.get_xticklabels()] == ["2026", "2027"]
    tops = [bar.get_y() + bar.get_height() for bar in _bars(ax)]
    assert tops == [1, 2, 4, 6]  # a's bars, then b's stacked on them


def test_plot_stacked_bar_stacks_negatives_below_zero() -> None:
    df = pd.DataFrame({"a": [-1.0], "b": [2.0], "c": [-3.0]}, index=pd.Index([2026]))

    ax = plot_stacked_bar(df, ["a", "b", "c"], ["#111111", "#222222", "#333333"], title="t")

    assert [(bar.get_y(), bar.get_height()) for bar in _bars(ax)] == [(0, -1), (0, 2), (-1, -3)]



def test_plot_stacked_bar_draws_every_column_with_a_short_palette() -> None:
    df = pd.DataFrame({"a": [1.0], "b": [2.0], "c": [3.0]}, index=pd.Index([2026]))

    ax = plot_stacked_bar(df, ["a", "b", "c"], ["#111111"], title="t")

    assert [bar.get_y() + bar.get_height() for bar in _bars(ax)] == [1, 3, 6]
    assert len({bar.get_facecolor() for bar in _bars(ax)}) == 1

def test_plot_income_expense_net_returns_axes() -> None:
    net = pd.DataFrame(
        {"income": [100.0], "expenses": [40.0], "net": [60.0]},
        index=pd.Index([2026], name="year"),
    )

    ax = plot_income_expense_net(net, title="net income")

    assert ax.get_title() == "net income"


def test_include_zero_gives_headroom_above_a_near_flat_positive_series() -> None:
    """A low-volatility series far from zero must not end up flush against
    the top spine once zero is forced into view (that's what made a line
    like 'Home' effectively disappear)."""
    ax = Figure().subplots()
    ax.plot(range(10), [700_000 + i for i in range(10)])
    include_zero(ax)

    lo, hi = ax.get_ylim()
    assert lo == 0.0
    assert hi > 700_009 + 1_000  # real headroom above the data max, not flush


def test_include_zero_anchors_top_for_all_negative_series() -> None:
    ax = Figure().subplots()
    ax.plot(range(5), [-100.0, -105.0, -110.0, -108.0, -112.0])
    include_zero(ax)

    lo, hi = ax.get_ylim()
    assert hi == 0.0
    assert lo < -112.0  # headroom below the data min


def test_include_zero_pads_both_ends_when_data_spans_zero() -> None:
    ax = Figure().subplots()
    ax.plot(range(4), [-50.0, 20.0, -10.0, 40.0])
    include_zero(ax)

    lo, hi = ax.get_ylim()
    assert lo < -50.0
    assert hi > 40.0
