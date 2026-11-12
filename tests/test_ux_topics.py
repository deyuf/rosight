"""Topics UX: unsubscribe, subscribed marker, plot without tab jump, exports."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, TabbedContent

from rosight.app import RosightApp
from rosight.ros.backend import RosBackend, Subscription, TopicInfo
from rosight.ros.discovery import GraphSnapshot
from rosight.widgets.topics_panel import TopicsPanel


class _Ros:
    def __init__(self):
        self.started = True
        self.executor_alive = True
        self.domain_id = 0
        self.subs: dict[str, Subscription] = {}
        self.snap = GraphSnapshot(
            topics=(TopicInfo("/odom", ("nav_msgs/msg/Odometry",), 1, 0),), generation=1
        )

    def graph_snapshot(self):
        return self.snap

    def active_subscriptions(self):
        return list(self.subs.values())

    def get_subscription(self, topic):
        return self.subs.get(topic)

    def subscribe(self, topic, type_name=None, **_kw):
        self.subs[topic] = Subscription(topic, type_name or "?")
        return self.subs[topic]

    def unsubscribe(self, topic):
        self.subs.pop(topic, None)

    def stop(self):
        pass


async def _topics(pilot):
    pilot.app.query_one(TabbedContent).active = "topics"
    for _ in range(2):
        await pilot.pause()
    return pilot.app.query_one(TopicsPanel)


def _first_cell(pilot) -> str:
    t = pilot.app.query_one("#topics-table", DataTable)
    return t.get_row_at(0)[0].plain


@pytest.mark.asyncio
async def test_x_unsubscribes_and_updates_marker():
    ros = _Ros()
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 40)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        panel = await _topics(pilot)
        panel._refresh_table()
        panel.selected_topic = "/odom"
        panel.action_echo()
        panel._render_table()
        assert _first_cell(pilot).startswith("●")

        panel.action_unsubscribe()
        assert "/odom" not in ros.subs
        assert not _first_cell(pilot).startswith("●")
        assert "unsubscribed /odom" in pilot.app.query_one("#status").message


@pytest.mark.asyncio
async def test_unsubscribe_warns_about_dependent_plot_series():
    ros = _Ros()
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 40)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        await _topics(pilot)
        pilot.app.add_plot_series("/odom", "twist.twist.linear.x")
        pilot.app.add_plot_series("/odom", "twist.twist.angular.z")
        assert "/odom" in ros.subs  # plot auto-subscribed
        assert pilot.app.unsubscribe_topic("/odom")
        assert "2 plot series paused" in pilot.app.query_one("#status").message


@pytest.mark.asyncio
async def test_unsub_command_single_and_all():
    ros = _Ros()
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 40)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        ros.subscribe("/a")
        ros.subscribe("/b")
        pilot.app._on_command_submitted("unsub /a")
        assert set(ros.subs) == {"/b"}
        pilot.app._on_command_submitted("unsub all")
        assert ros.subs == {}
        assert "unsubscribed 1 topic(s)" in pilot.app.query_one("#status").message
        pilot.app._on_command_submitted("unsub /nope")
        assert "not subscribed" in pilot.app.query_one("#status").message


@pytest.mark.asyncio
async def test_hz_bw_bindings_removed():
    keys = {b.key for b in TopicsPanel.BINDINGS}
    assert "h" not in keys and "b" not in keys
    assert "x" in keys


@pytest.mark.asyncio
async def test_adding_plot_field_stays_on_current_tab():
    ros = _Ros()
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 40)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        await _topics(pilot)
        pilot.app.add_plot_series("/odom", "pose.pose.position.x")
        await pilot.pause()
        assert pilot.app.query_one(TabbedContent).active == "topics"
        # The explicit :plot command still jumps.
        pilot.app._on_command_submitted("plot /odom pose.pose.position.y")
        await pilot.pause()
        assert pilot.app.query_one(TabbedContent).active == "plot"


@pytest.mark.asyncio
async def test_export_path_honours_config(tmp_path):
    app = RosightApp(ros=RosBackend())
    target = tmp_path / "exports" / "nested"
    app.config = replace(app.config, ui=replace(app.config.ui, export_dir=str(target)))
    out = app.export_path("x.csv")
    assert out == (target / "x.csv").resolve()
    assert target.is_dir(), "export_dir is created on demand"


@pytest.mark.asyncio
async def test_export_path_defaults_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = RosightApp(ros=RosBackend())
    assert app.export_path("y.png") == (tmp_path / "y.png").resolve()


@pytest.mark.asyncio
async def test_plot_csv_goes_to_export_dir(tmp_path):
    ros = _Ros()
    app = RosightApp(ros=RosBackend())
    app.config = replace(app.config, ui=replace(app.config.ui, export_dir=str(tmp_path)))
    async with app.run_test(headless=True, size=(160, 40)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        from rosight.widgets.plot_panel import PlotPanel

        panel = pilot.app.query_one(PlotPanel)
        panel.add_series("/odom", "pose.pose.position.x")
        panel.plot.push("/odom/pose.pose.position.x", 1.0)
        panel.action_save_csv()
    files = list(Path(tmp_path).glob("rosight-*.csv"))
    assert len(files) == 1
