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

from rosight.app import RosightApp
from rosight.ros.backend import RosBackend
from rosight.widgets.interfaces_panel import InterfacesPanel
from rosight.widgets.nodes_panel import NodesPanel
from rosight.widgets.services_panel import ServicesPanel
from rosight.widgets.topics_panel import TopicsPanel

_TOPIC_NAME = "/rosight_it_topic"

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


def _new_app() -> RosightApp:
    backend = RosBackend(node_name=f"rosight_it_{int(time.monotonic() * 1000)}")
    app = RosightApp(ros=backend)
    # Passing ``ros=`` means the app doesn't own the backend and therefore
    # never started it — every test below used to skip itself. Let the app
    # start and stop it like in production.
    app._owns_ros = True
    return app


def _snapshot_has_topic(app: RosightApp, topic: str) -> bool:
    """Panels read the background graph snapshot, which can lag
    ``list_topics()`` by up to one discovery period."""
    app.ros.request_graph_refresh()
    return any(t.name == topic for t in app.ros.graph_snapshot().topics)


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
        found = await _wait_for(lambda: _snapshot_has_topic(app, _TOPIC_NAME))
        assert found, "publisher topic never showed up in the graph snapshot"
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
        await _wait_for(lambda: _snapshot_has_topic(app, _TOPIC_NAME))
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
        await _wait_for(lambda: _snapshot_has_topic(app, _TOPIC_NAME))
        panel = pilot.app.query_one(TopicsPanel)
        panel._refresh_table()
        panel.selected_topic = _TOPIC_NAME
        panel.action_echo()
        await pilot.pause()
        sub = app.ros.get_subscription(_TOPIC_NAME)
        assert sub is not None, "action_echo didn't create a subscription"
        got = await _wait_for(lambda: sub.last_msg is not None, timeout=5.0)
        assert got, "no message received after subscribe"
        # Raw subscription path: bytes in, decoded lazily on read.
        assert sub.raw_mode, "expected a raw subscription on a real rclpy"
        assert sub.last_msg.data == "hello"
        assert sub.bandwidth.sample().avg_msg_size > 0
        assert await _wait_for(lambda: sub.rate.sample().hz > 5, timeout=5.0)


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
        await _wait_for(lambda: len(app.ros.graph_snapshot().services) > 0, timeout=8.0)
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
        # The rosight backend plus the ros2 topic pub node should both
        # show up (>= 2 nodes total).
        await _wait_for(lambda: len(app.ros.graph_snapshot().nodes) >= 2, timeout=8.0)
        # Hidden panels skip refreshes on purpose; show the tab first.
        pilot.app.query_one(TabbedContent).active = "nodes"
        await pilot.pause()
        panel = pilot.app.query_one(NodesPanel)
        panel._refresh(force=True)
        await pilot.pause()
        table = panel.query_one("#nodes-table", DataTable)
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
        await _wait_for(lambda: _snapshot_has_topic(app, _TOPIC_NAME))
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


# ---------------------------------------------------------------------------
# Real-rclpy coverage for paths that otherwise only have fakes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parameter_round_trip_on_own_node():
    """list / get / set parameters through real services (our own node)."""
    app = _new_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        if not app.ros.started:
            pytest.skip("RosBackend failed to start in this environment")
        fqn = f"/{app.ros.node_name}"
        names = await asyncio.to_thread(app.ros.list_parameters, fqn)
        assert "use_sim_time" in names
        (before,) = await asyncio.to_thread(app.ros.get_parameters, fqn, ["use_sim_time"])
        assert before.type_name == "bool" and before.value is False
        ok = await asyncio.to_thread(app.ros.set_parameter, fqn, "use_sim_time", True, "bool")
        assert ok
        (after,) = await asyncio.to_thread(app.ros.get_parameters, fqn, ["use_sim_time"])
        assert after.value is True


@pytest.mark.asyncio
async def test_publish_once_reaches_our_own_subscription():
    app = _new_app()
    async with app.run_test(headless=True, size=(160, 50)) as pilot:
        await pilot.pause()
        if not app.ros.started:
            pytest.skip("RosBackend failed to start in this environment")
        from rosight.ros.introspection import get_message_class
        from rosight.ros.yaml_msg import yaml_to_message

        topic = "/rosight_it_publish"
        string_cls = get_message_class("std_msgs/msg/String")
        sub = app.ros.subscribe(topic, "std_msgs/msg/String")
        msg = yaml_to_message("data: from-form", string_cls)

        async def publish_until_received() -> bool:
            for _ in range(10):
                await asyncio.to_thread(app.ros.publish_once, topic, "std_msgs/msg/String", msg)
                if await _wait_for(lambda: sub.last_msg is not None, timeout=0.5):
                    return True
            return False

        assert await publish_until_received()
        assert sub.last_msg.data == "from-form"


def test_yaml_forms_with_real_message_types():
    from rosight.ros.introspection import get_message_class
    from rosight.ros.yaml_msg import MessageYamlError, message_to_yaml, yaml_to_message

    twist_cls = get_message_class("geometry_msgs/msg/Twist")
    msg = yaml_to_message("linear: {x: 1}\nangular: {z: -0.5}", twist_cls)
    assert msg.linear.x == 1.0 and msg.angular.z == -0.5
    assert yaml_to_message(message_to_yaml(msg), twist_cls) == msg
    with pytest.raises(MessageYamlError, match=r"unknown field 'linear\.w'"):
        yaml_to_message("linear: {w: 1}", twist_cls)
    with pytest.raises(MessageYamlError, match="nested message"):
        yaml_to_message("linear: 3", twist_cls)
    with pytest.raises(MessageYamlError):
        yaml_to_message("linear: {x: fast}", twist_cls)
