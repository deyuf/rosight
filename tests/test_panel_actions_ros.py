"""ROS 2 integration tests for panel actions.

Requires a sourced ROS 2 environment (``rclpy`` + ``ros2`` CLI). The publisher
runs in a separate ``ros2 topic pub`` subprocess so it has its own DDS
participant — same-process Python publishers in a second ``rclpy.Context``
don't always discover each other via shared-memory transports.

Skipped automatically when rclpy or the ``ros2`` CLI aren't available.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import time
from collections.abc import Iterator

import pytest

pytest.importorskip("rclpy")
pytest.importorskip("textual")

from textual.widgets import DataTable, Static, TabbedContent

from lazyrosplus.app import LazyrosPlusApp
from lazyrosplus.ros.backend import RosBackend
from lazyrosplus.widgets.interfaces_panel import InterfacesPanel
from lazyrosplus.widgets.nodes_panel import NodesPanel
from lazyrosplus.widgets.services_panel import ServicesPanel
from lazyrosplus.widgets.topics_panel import TopicsPanel

_TOPIC_NAME = "/lazyrosplus_it_topic"

# Skip the entire module if `ros2` isn't on PATH — these tests need it for the
# out-of-process publisher.
if shutil.which("ros2") is None:
    pytest.skip("`ros2` CLI not on PATH", allow_module_level=True)


@pytest.fixture(scope="module")
def ros2_publisher() -> Iterator[subprocess.Popen[bytes]]:
    """Run `ros2 topic pub` as the test publisher in its own process."""
    proc = subprocess.Popen(
        [
            "ros2",
            "topic",
            "pub",
            "--rate",
            "20",
            _TOPIC_NAME,
            "std_msgs/msg/String",
            '{data: "hello"}',
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env={**os.environ},
    )
    # Give DDS a moment to register the publisher.
    time.sleep(2.0)
    try:
        yield proc
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


async def _wait_for(check, *, timeout: float = 10.0, step: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        await asyncio.sleep(step)
    return False


def _new_app() -> LazyrosPlusApp:
    backend = RosBackend(node_name=f"lazyrosplus_it_{int(time.monotonic() * 1000)}")
    return LazyrosPlusApp(ros=backend)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topics_panel_discovers_running_publisher(ros2_publisher):
    app = _new_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        if not app.ros.started:
            pytest.skip("RosBackend failed to start in this environment")
        found = await _wait_for(lambda: any(t.name == _TOPIC_NAME for t in app.ros.list_topics()))
        assert found, "publisher topic never showed up in list_topics()"
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


# ---------------------------------------------------------------------------
# Topic actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_topics_info_writes_real_info_to_info_area(ros2_publisher):
    app = _new_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        if not app.ros.started:
            pytest.skip("RosBackend failed to start in this environment")
        await _wait_for(lambda: any(t.name == _TOPIC_NAME for t in app.ros.list_topics()))
        panel = pilot.app.query_one(TopicsPanel)
        panel._refresh_table()
        panel.selected_topic = _TOPIC_NAME
        panel.action_info()
        await pilot.pause()
        info_area = pilot.app.query_one("#info-area", Static)
        rendered = str(getattr(info_area, "renderable", "") or getattr(info_area, "content", ""))
        assert _TOPIC_NAME in rendered
        assert "std_msgs/msg/String" in rendered


@pytest.mark.asyncio
async def test_topics_bw_subscribes_and_receives_message(ros2_publisher):
    app = _new_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        if not app.ros.started:
            pytest.skip("RosBackend failed to start in this environment")
        await _wait_for(lambda: any(t.name == _TOPIC_NAME for t in app.ros.list_topics()))
        panel = pilot.app.query_one(TopicsPanel)
        panel._refresh_table()
        panel.selected_topic = _TOPIC_NAME
        panel.action_bw()  # alias for action_echo: subscribes
        await pilot.pause()
        sub = app.ros.get_subscription(_TOPIC_NAME)
        assert sub is not None, "action_bw didn't create a subscription"
        got = await _wait_for(lambda: sub.last_msg is not None, timeout=5.0)
        assert got, "no message received after subscribe"


# ---------------------------------------------------------------------------
# Other tabs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interfaces_tab_does_not_crash(ros2_publisher):
    """Regression for `_render` shadowing `Widget._render` in InterfacesPanel."""
    app = _new_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        pilot.app.query_one(TabbedContent).active = "interfaces"
        await pilot.pause()
        panel = pilot.app.query_one(InterfacesPanel)
        # If the `_render` shadowing bug were back, switching the tab would
        # raise `'NoneType' object has no attribute 'render_strips'` from the
        # compositor and tear the app down before this line runs.
        assert panel.is_mounted


@pytest.mark.asyncio
async def test_services_tab_lists_default_services(ros2_publisher):
    app = _new_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        if not app.ros.started:
            pytest.skip("RosBackend failed to start in this environment")
        # Every rclpy node exposes default services (get_parameters, …).
        await _wait_for(lambda: len(app.ros.list_services()) > 0, timeout=8.0)
        pilot.app.query_one(TabbedContent).active = "services"
        await pilot.pause()
        panel = pilot.app.query_one(ServicesPanel)
        panel._refresh()
        await pilot.pause()
        table = pilot.app.query_one("#srv-table", DataTable)
        assert table.row_count > 0


@pytest.mark.asyncio
async def test_nodes_panel_sees_publisher_process(ros2_publisher):
    app = _new_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        if not app.ros.started:
            pytest.skip("RosBackend failed to start in this environment")
        # The lazyrosplus backend plus the ros2 topic pub node should both
        # show up (>= 2 nodes total).
        await _wait_for(lambda: len(app.ros.list_nodes()) >= 2, timeout=8.0)
        panel = pilot.app.query_one(NodesPanel)
        panel._refresh()
        await pilot.pause()
        table = pilot.app.query_one("#nodes-table", DataTable)
        assert table.row_count >= 2


# ---------------------------------------------------------------------------
# Cursor preservation across refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cursor_stays_on_selected_topic_across_refresh(ros2_publisher):
    """Regression: the periodic _refresh_table reset cursor to row 0."""
    app = _new_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        if not app.ros.started:
            pytest.skip("RosBackend failed to start in this environment")
        await _wait_for(lambda: any(t.name == _TOPIC_NAME for t in app.ros.list_topics()))
        panel = pilot.app.query_one(TopicsPanel)
        panel._refresh_table()
        await pilot.pause()
        table = pilot.app.query_one("#topics-table", DataTable)
        target = -1
        for i in range(table.row_count):
            row_key, _ = table.coordinate_to_cell_key((i, 0))
            if row_key and str(row_key.value) == _TOPIC_NAME:
                target = i
                break
        assert target >= 0
        table.move_cursor(row=target, animate=False)
        await pilot.pause()
        for _ in range(3):
            panel._refresh_table()
            await pilot.pause()
        row_key, _ = table.coordinate_to_cell_key((table.cursor_row, 0))
        assert row_key is not None
        assert str(row_key.value) == _TOPIC_NAME
