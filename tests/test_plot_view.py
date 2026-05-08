from __future__ import annotations

from lazyrosplus.widgets.plot_view import PlotSeries, assign_color


def test_assign_color_cycles():
    a = assign_color(0)
    b = assign_color(1)
    assert a != b
    # cycles after the palette length
    assert assign_color(0) == assign_color(10)


def test_plot_series_push_and_stats():
    s = PlotSeries(label="x")
    for v in [1.0, 2.0, 3.0, 4.0, 5.0]:
        s.push(v)
    stats = s.stats()
    assert stats is not None
    mn, mx, mean, last = stats
    assert mn == 1.0
    assert mx == 5.0
    assert mean == 3.0
    assert last == 5.0


def test_plot_series_empty_stats_returns_none():
    s = PlotSeries(label="empty")
    assert s.stats() is None
    assert s.latest is None
