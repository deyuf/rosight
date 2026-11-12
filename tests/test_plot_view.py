from __future__ import annotations

import pytest

from rosight.widgets.plot_view import PlotSeries, SnapshotSeries, assign_color


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


def test_snapshot_series_stats_min_max_len():
    s = SnapshotSeries(label="snap")
    assert s.stats() is None
    s.set_latest([3.0, 1.0, 4.0, 1.5, 9.0])
    stat = s.stats()
    assert stat is not None
    mn, mx, ln = stat
    assert mn == 1.0
    assert mx == 9.0
    assert ln == 5


def test_snapshot_series_set_latest_overwrites():
    s = SnapshotSeries(label="snap")
    s.set_latest([1, 2, 3])
    s.set_latest([10])
    assert s.values == [10.0]


@pytest.mark.asyncio
async def test_mixed_plot_does_not_duplicate_subplots_across_frames():
    """Regression: with time + snapshot series, every frame after the first
    drew the snapshot subplot twice (plotext's clf() cleared only the
    active subplot, so the next subplots(2, 1) nested inside it)."""
    pytest.importorskip("plotext")
    from textual.app import App, ComposeResult

    from rosight.widgets.plot_view import PlotView

    class _App(App):
        def compose(self) -> ComposeResult:
            yield PlotView(id="pv")

    async with _App().run_test(size=(120, 40)) as pilot:
        pv = pilot.app.query_one(PlotView)
        pv.add_series("speed")
        for i in range(20):
            pv.push("speed", float(i), None)
        pv.add_snapshot_series("ranges")
        pv.push_snapshot("ranges", [1.0, 2.0, 3.0, 2.0])
        await pilot.pause()
        for _ in range(3):
            plain = pv._build_content().plain
            # One time subplot ("seconds" axis) and one snapshot subplot
            # ("index" axis) — never more, however many frames rendered.
            assert plain.count("seconds") == 1, plain
            assert plain.count("index") == 1, plain
