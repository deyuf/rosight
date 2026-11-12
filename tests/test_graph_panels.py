"""Panels driven by the graph snapshot, plus app-level health handling."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from rich.text import Text
from textual.widgets import DataTable, TabbedContent

from rosight.app import RosightApp
from rosight.ros.backend import RosBackend, ServiceInfo, Subscription, TopicInfo
from rosight.ros.discovery import EMPTY_SNAPSHOT, GraphSnapshot
from rosight.widgets._base import PLACEHOLDER_KEY
from rosight.widgets.services_panel import ServicesPanel
from rosight.widgets.status_bar import StatusBar
from rosight.widgets.topics_panel import TopicsPanel


class _FakeRos:
    """Duck-typed backend exposing the snapshot API."""

    def __init__(self, snap: GraphSnapshot = EMPTY_SNAPSHOT):
        self.started = True
        self.executor_alive = True
        self.last_error = None
        self.domain_id = 0
        self.snap = snap
        self.snapshot_reads = 0
        self.subs: list[Subscription] = []
        self.refresh_requests = 0
        self.restarts = 0

    def graph_snapshot(self) -> GraphSnapshot:
        self.snapshot_reads += 1
        return self.snap

    def request_graph_refresh(self) -> None:
        self.refresh_requests += 1

    def active_subscriptions(self):
        return list(self.subs)

    def get_subscription(self, topic):
        return next((s for s in self.subs if s.topic == topic), None)

    def restart(self):
        self.restarts += 1
        self.executor_alive = True

    def stop(self):
        pass


def _snap(gen: int, services=(), topics=()) -> GraphSnapshot:
    return GraphSnapshot(topics=tuple(topics), services=tuple(services), generation=gen)


def _cells(table: DataTable) -> list[list[str]]:
    out = []
    for row in table.ordered_rows:
        out.append([str(getattr(c, "plain", c)) for c in table.get_row(row.key)])
    return out


async def _show(pilot, tab: str):
    pilot.app.query_one(TabbedContent).active = tab
    for _ in range(3):
        await pilot.pause()


@pytest.mark.asyncio
async def test_list_panel_skips_render_when_generation_unchanged():
    ros = _FakeRos(_snap(1, services=[ServiceInfo("/a", ("std_srvs/srv/Empty",))]))
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(140, 40)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        await _show(pilot, "services")
        panel = pilot.app.query_one(ServicesPanel)
        panel._refresh(force=True)
        renders = {"n": 0}
        orig = panel._render_table
        panel._render_table = lambda: (renders.__setitem__("n", renders["n"] + 1), orig())[1]
        for _ in range(5):
            panel._refresh()
        assert renders["n"] == 0, "unchanged generation must not re-render"
        ros.snap = _snap(
            2,
            services=[
                ServiceInfo("/a", ("std_srvs/srv/Empty",)),
                ServiceInfo("/b", ("std_srvs/srv/Trigger",)),
            ],
        )
        panel._refresh()
        assert renders["n"] == 1
        table = pilot.app.query_one("#srv-table", DataTable)
        assert [r[0] for r in _cells(table)] == ["/a", "/b"]


@pytest.mark.asyncio
async def test_list_panel_empty_states():
    app = RosightApp(ros=RosBackend())  # never started
    async with app.run_test(headless=True, size=(140, 40)) as pilot:
        await _show(pilot, "services")
        table = pilot.app.query_one("#srv-table", DataTable)
        assert _cells(table)[0][0] == "ROS backend not running"

        ros = _FakeRos(EMPTY_SNAPSHOT)
        pilot.app.ros = ros  # type: ignore[assignment]
        panel = pilot.app.query_one(ServicesPanel)
        panel._refresh(force=True)
        assert _cells(table)[0][0] == "discovering…"

        ros.snap = _snap(1)
        panel._refresh()
        assert _cells(table)[0][0] == "no services on this ROS domain"

        ros.snap = _snap(2, services=[ServiceInfo("/add_two_ints", ("x/srv/AddTwoInts",))])
        panel._refresh()
        panel.filter_text = "zzz"
        panel._render_table()
        assert _cells(table)[0][0] == "no services match 'zzz'"
        # Highlighting the placeholder must not select it.
        assert panel.selected is None or panel.selected != PLACEHOLDER_KEY


@pytest.mark.asyncio
async def test_list_panel_fuzzy_filter():
    ros = _FakeRos(
        _snap(
            1,
            services=[
                ServiceInfo("/add_two_ints", ("example_interfaces/srv/AddTwoInts",)),
                ServiceInfo("/talker/get_parameters", ("rcl_interfaces/srv/GetParameters",)),
            ],
        )
    )
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(140, 40)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        await _show(pilot, "services")
        panel = pilot.app.query_one(ServicesPanel)
        panel._refresh(force=True)
        panel.filter_text = "ati"  # subsequence of "add_two_ints" only
        panel._render_table()
        table = pilot.app.query_one("#srv-table", DataTable)
        assert [r[0] for r in _cells(table)] == ["/add_two_ints"]
        panel.filter_text = "getparam"
        panel._render_table()
        assert [r[0] for r in _cells(table)] == ["/talker/get_parameters"]


@pytest.mark.asyncio
async def test_topics_table_trend_and_qos_cells():
    ros = _FakeRos(_snap(1, topics=[TopicInfo("/scan", ("sensor_msgs/msg/LaserScan",), 1, 0)]))
    sub = Subscription("/scan", "sensor_msgs/msg/LaserScan")
    ros.subs = [sub]
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(160, 40)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        await _show(pilot, "topics")
        panel = pilot.app.query_one(TopicsPanel)
        for _ in range(3):
            panel._refresh_table()
        table = pilot.app.query_one("#topics-table", DataTable)
        row = _cells(table)[0]
        assert row[0] == "● /scan", "subscribed rows carry a marker"
        assert row[5] == "▁▁▁", "three zero-Hz samples → flat trend"

        sub.on_incompatible_qos(SimpleNamespace(total_count=2, last_policy_kind="RELIABILITY"))
        panel._refresh_table()
        hz_cell = table.get_row("/scan")[4]
        assert isinstance(hz_cell, Text) and hz_cell.plain == "QoS!"

        panel.selected_topic = "/scan"
        panel._refresh_detail()
        header = pilot.app.query_one("#detail-header")
        rendered = str(header.render())
        assert "incompatible QoS" in rendered and "reliability" in rendered


@pytest.mark.asyncio
async def test_status_bar_reads_snapshot_not_list_calls():
    ros = _FakeRos(
        _snap(
            1,
            services=[ServiceInfo("/s", ("t",))],
            topics=[TopicInfo("/a", ("t",)), TopicInfo("/b", ("t",))],
        )
    )
    ros.list_topics = lambda: pytest.fail("status bar must not call list_topics")  # type: ignore[attr-defined]
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(140, 40)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        pilot.app.backend_ok = True
        pilot.app._refresh_status()
        bar = pilot.app.query_one("#status", StatusBar)
        assert (bar.topics, bar.services) == (2, 1)
        assert bar.backend_ok


@pytest.mark.asyncio
async def test_dead_executor_turns_status_red_and_notifies_once():
    ros = _FakeRos(_snap(1))
    ros.executor_alive = False
    ros.last_error = "RuntimeError: boom"
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(140, 40)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        pilot.app.backend_ok = True
        notes: list = []
        pilot.app.notify = lambda *a, **kw: notes.append((a, kw))  # type: ignore[method-assign]
        for _ in range(5):
            pilot.app._refresh_status()
        bar = pilot.app.query_one("#status", StatusBar)
        assert bar.backend_ok is False
        assert len(notes) == 1, "must not spam a notification every tick"
        assert "boom" in notes[0][0][0] and ":reconnect" in notes[0][0][0]
        assert "reconnect" in bar.message

        pilot.app._on_command_submitted("reconnect")
        for _ in range(10):
            await pilot.pause()
            if ros.restarts:
                break
        assert ros.restarts == 1
        pilot.app._refresh_status()
        assert bar.backend_ok is True


@pytest.mark.asyncio
async def test_refresh_key_wakes_graph_monitor():
    ros = _FakeRos(_snap(1))
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(140, 40)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        pilot.app.action_refresh()
        assert ros.refresh_requests == 1


@pytest.mark.asyncio
async def test_status_ticker_tolerates_missing_status_bar():
    """The 1 Hz status timer can fire while the app tears its screen down
    (seen on CI): ``#status`` is already gone and ``query_one`` raised
    NoMatches, failing an unrelated test. The tick must just no-op."""
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(140, 40)) as pilot:
        await pilot.app.query_one("#status", StatusBar).remove()
        await pilot.pause()
        pilot.app._refresh_status()  # must not raise
