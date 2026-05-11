"""ROS 2 integration tests for panel actions.

These tests require ``rclpy`` (i.e. a sourced ROS 2 environment). They are
skipped automatically when rclpy can't be imported, and run in the
``ros-integration`` CI job inside ``ros:humble`` / ``ros:jazzy`` containers.

The test fixture spins a small publisher node in a background thread so the
app sees a real, ticking topic over DDS — no mocks.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Iterator

import pytest

pytest.importorskip("rclpy")
pytest.importorskip("textual")

import rclpy
from rclpy.executors import SingleThreadedExecutor
from std_msgs.msg import String
from textual.widgets import DataTable, Static, TabbedContent

from lazyrosplus.app import LazyrosPlusApp
from lazyrosplus.ros.backend import RosBackend
from lazyrosplus.widgets.interfaces_panel import InterfacesPanel
from lazyrosplus.widgets.nodes_panel import NodesPanel
from lazyrosplus.widgets.services_panel import ServicesPanel
from lazyrosplus.widgets.topics_panel import TopicsPanel

_TOPIC_NAME = "/lazyrosplus_it_topic"
_PUB_NODE_NAME = "lazyrosplus_it_publisher"
_APP_NODE_NAME = "lazyrosplus_it_app"


@pytest.fixture(scope="module")
def _rclpy_publisher() -> Iterator[None]:
    """Start a String publisher in a dedicated rclpy context for the module."""
    pub_ctx = rclpy.Context()
    rclpy.init(context=pub_ctx)
    node = rclpy.create_node(_PUB_NODE_NAME, context=pub_ctx)
    pub = node.create_publisher(String, _TOPIC_NAME, 10)
    stop = threading.Event()

    def loop() -> None:
        executor = SingleThreadedExecutor(context=pub_ctx)
        executor.add_node(node)
        next_pub = 0.0
        while not stop.is_set():
            now = time.monotonic()
            if now >= next_pub:
                msg = String()
                msg.data = f"hello @ {now:.3f}"
                pub.publish(msg)
                next_pub = now + 0.1
            executor.spin_once(timeout_sec=0.05)
        executor.shutdown()

    thread = threading.Thread(target=loop, name="it-publisher", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=2)
        try:
            node.destroy_node()
        finally:
            rclpy.shutdown(context=pub_ctx)


async def _wait_for(check, *, timeout: float = 5.0, step: float = 0.1) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        await asyncio.sleep(step)
    return False


async def _running_app(pilot_size: tuple[int, int] = (160, 50)):
    """Helper: start an app whose backend connects to live DDS."""
    backend = RosBackend(node_name=_APP_NODE_NAME)
    return LazyrosPlusApp(ros=backend)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topics_panel_discovers_running_publisher(_rclpy_publisher):
    app = await _running_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        found = await _wait_for(lambda: any(t.name == _TOPIC_NAME for t in app.ros.list_topics()))
        assert found, "publisher topic never showed up in list_topics()"

        # Force the panel to refresh and verify the row is present.
        panel = pilot.app.query_one(TopicsPanel)
        panel._refresh_table()
        await pilot.pause()
        table = pilot.app.query_one("#topics-table", DataTable)
        seen = []
        for i in range(table.row_count):
            row_key, _ = table.coordinate_to_cell_key((i, 0))
            if row_key:
                seen.append(str(row_key.value))
        assert _TOPIC_NAME in seen


@pytest.mark.asyncio
async def test_nodes_panel_lists_publisher_node(_rclpy_publisher):
    app = await _running_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        await _wait_for(lambda: any(_PUB_NODE_NAME in n.fqn for n in app.ros.list_nodes()))
        panel = pilot.app.query_one(NodesPanel)
        panel._refresh()
        await pilot.pause()
        table = pilot.app.query_one("#nodes-table", DataTable)
        fqns = []
        for i in range(table.row_count):
            row_key, _ = table.coordinate_to_cell_key((i, 0))
            if row_key:
                fqns.append(str(row_key.value))
        assert any(_PUB_NODE_NAME in f for f in fqns)


# ---------------------------------------------------------------------------
# Topic actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topics_info_shows_real_topic_info(_rclpy_publisher):
    app = await _running_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        await _wait_for(lambda: any(t.name == _TOPIC_NAME for t in app.ros.list_topics()))
        panel = pilot.app.query_one(TopicsPanel)
        panel._refresh_table()
        panel.selected_topic = _TOPIC_NAME
        panel.action_info()
        await pilot.pause()
        info_area = pilot.app.query_one("#info-area", Static)
        rendered = str(getattr(info_area, "renderable", "") or info_area.content)
        assert _TOPIC_NAME in rendered
        assert "std_msgs/msg/String" in rendered


@pytest.mark.asyncio
async def test_topics_bw_subscribes(_rclpy_publisher):
    app = await _running_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        await _wait_for(lambda: any(t.name == _TOPIC_NAME for t in app.ros.list_topics()))
        panel = pilot.app.query_one(TopicsPanel)
        panel._refresh_table()
        panel.selected_topic = _TOPIC_NAME
        panel.action_bw()
        await pilot.pause()
        # Subscription should exist (action_bw == action_echo)
        sub = app.ros.get_subscription(_TOPIC_NAME)
        assert sub is not None
        # Wait for at least one message to arrive so hz/bw becomes non-zero.
        got_message = await _wait_for(lambda: sub.last_msg is not None, timeout=3.0)
        assert got_message, "no message received after subscribe"


@pytest.mark.asyncio
async def test_topics_hz_subscribes(_rclpy_publisher):
    app = await _running_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        await _wait_for(lambda: any(t.name == _TOPIC_NAME for t in app.ros.list_topics()))
        panel = pilot.app.query_one(TopicsPanel)
        panel._refresh_table()
        panel.selected_topic = _TOPIC_NAME
        panel.action_hz()
        await pilot.pause()
        assert app.ros.get_subscription(_TOPIC_NAME) is not None


# ---------------------------------------------------------------------------
# Other tabs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interfaces_tab_does_not_crash(_rclpy_publisher):
    """Was the bug that pressing the Interfaces tab crashed the app."""
    app = await _running_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        pilot.app.query_one(TabbedContent).active = "interfaces"
        await pilot.pause()
        # If we got here without an AttributeError on _render, the bug is gone.
        panel = pilot.app.query_one(InterfacesPanel)
        # Discovery may find zero interfaces in a stripped container; just
        # require that the panel is mounted and queryable.
        assert panel.is_mounted


@pytest.mark.asyncio
async def test_services_tab_loads(_rclpy_publisher):
    app = await _running_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        pilot.app.query_one(TabbedContent).active = "services"
        await pilot.pause()
        panel = pilot.app.query_one(ServicesPanel)
        # The publisher node we spawned doesn't expose a service, but rclpy
        # always exposes some default ones (/<node>/get_parameters, etc.).
        await _wait_for(lambda: len(app.ros.list_services()) > 0)
        panel._refresh()
        await pilot.pause()
        table = pilot.app.query_one("#srv-table", DataTable)
        assert table.row_count > 0


# ---------------------------------------------------------------------------
# Cursor preservation across the refresh tick
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cursor_stays_on_selected_topic_across_refresh(_rclpy_publisher):
    """Regression: re-rendering the table was resetting the cursor to row 0."""
    app = await _running_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        await _wait_for(lambda: any(t.name == _TOPIC_NAME for t in app.ros.list_topics()))
        panel = pilot.app.query_one(TopicsPanel)
        panel._refresh_table()
        await pilot.pause()
        table = pilot.app.query_one("#topics-table", DataTable)
        # Find the row index for our integration topic and move cursor there.
        target_idx = -1
        for i in range(table.row_count):
            row_key, _ = table.coordinate_to_cell_key((i, 0))
            if row_key and str(row_key.value) == _TOPIC_NAME:
                target_idx = i
                break
        assert target_idx >= 0
        table.move_cursor(row=target_idx, animate=False)
        await pilot.pause()
        # Trigger several refreshes — the cursor must stay on _TOPIC_NAME.
        for _ in range(3):
            panel._refresh_table()
            await pilot.pause()
        row_key, _ = table.coordinate_to_cell_key((table.cursor_row, 0))
        assert row_key is not None
        assert str(row_key.value) == _TOPIC_NAME
