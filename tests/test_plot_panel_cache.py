"""Tests for the PathStep caching in PlotPanel.

``add_series`` parses the field path once and stores the resulting
``list[PathStep]`` alongside the source tuple. Regression goal: every
sample tick previously called ``parse_path(field_path)`` again, which
is a regex pass per series per tick. We verify the parsed list is
cached and that ``_sample`` no longer calls ``parse_path``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from rosight.app import RosightApp
from rosight.ros.backend import RosBackend
from rosight.utils.path import PathStep
from rosight.widgets.plot_panel import PlotPanel


def _app() -> RosightApp:
    return RosightApp(ros=RosBackend())


class _FakeMsg:
    def __init__(self, x: float):
        self.x = x


class _Sub:
    def __init__(self, msg):
        self.last_msg = msg
        self.last_msg_ts = 0.0

    def snapshot(self):
        return self.last_msg, self.last_msg_ts


class _Ros:
    def __init__(self, sub):
        self._sub = sub
        self.started = True

    def get_subscription(self, _topic):
        return self._sub

    def subscribe(self, _topic, *a, **kw):
        return self._sub


@pytest.mark.asyncio
async def test_add_series_caches_parsed_path():
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one("TabbedContent").active = "plot"
        await pilot.pause()
        panel = pilot.app.query_one(PlotPanel)
        panel.add_series("/topic", "x")
        assert "/topic/x" in panel._sources
        topic, raw, kind, steps = panel._sources["/topic/x"]
        assert topic == "/topic"
        assert raw == "x"
        assert kind == "scalar"
        assert steps == [PathStep(name="x")]


@pytest.mark.asyncio
async def test_add_snapshot_series_caches_parsed_path():
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one("TabbedContent").active = "plot"
        await pilot.pause()
        panel = pilot.app.query_one(PlotPanel)
        panel.add_snapshot_series("/scan", "ranges")
        _, _, kind, steps = panel._sources["/scan/ranges"]
        assert kind == "array"
        assert steps == [PathStep(name="ranges")]


@pytest.mark.asyncio
async def test_add_series_invalid_path_is_rejected_safely(caplog):
    """A bad path used to leak ``ValueError`` from ``parse_path`` later;
    now ``add_series`` validates up front and logs a warning."""
    import logging

    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one("TabbedContent").active = "plot"
        await pilot.pause()
        panel = pilot.app.query_one(PlotPanel)
        with caplog.at_level(logging.WARNING, logger="rosight.widgets.plot_panel"):
            panel.add_series("/topic", "@#$")
        # Entry must NOT be in _sources if parsing failed.
        assert "/topic/@#$" not in panel._sources
        assert "invalid field path" in caplog.text


def test_sample_reuses_cached_steps(monkeypatch):
    """``_sample`` must not re-parse the path each tick — operates
    directly on a bare ``PlotPanel`` (no Textual mount) with mocked
    ``.ros`` and ``.plot`` properties."""
    import rosight.widgets.plot_panel as plot_panel_mod
    from rosight.widgets.plot_view import PlotView

    panel = PlotPanel()
    sub = _Sub(_FakeMsg(x=3.5))
    ros = _Ros(sub)
    pv = PlotView()
    monkeypatch.setattr(type(panel), "ros", property(lambda self: ros))
    monkeypatch.setattr(type(panel), "plot", property(lambda self: pv))

    panel.add_series("/topic", "x")

    parse_calls = {"n": 0}
    real_parse = plot_panel_mod.parse_path

    def counting_parse(*a, **kw):
        parse_calls["n"] += 1
        return real_parse(*a, **kw)

    monkeypatch.setattr(plot_panel_mod, "parse_path", counting_parse)

    # Run many sample ticks. ``parse_path`` must NOT be re-invoked.
    for _ in range(50):
        panel._sample()
    assert parse_calls["n"] == 0
    # And the latest scalar made it through:
    series = pv.series["/topic/x"]
    stat = series.stats()
    assert stat is not None
    assert stat[3] == 3.5  # latest value
