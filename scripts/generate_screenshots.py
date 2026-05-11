"""Generate SVG screenshots of every Rosight tab for the docs.

Why this exists:
    Running Rosight on a real terminal won't show off the layout cleanly
    (most contributors don't have a ROS network ready). This script runs
    the app under Textual's pilot harness with a stub backend, injects
    representative data into each panel, switches to each tab, and saves
    one SVG per tab into ``docs/screenshots/``.

Run with:
    python scripts/generate_screenshots.py
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from textual.widgets import Static, TabbedContent

from rosight.app import RosightApp
from rosight.ros.backend import RosBackend

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Stub data — duck-typed so it walks like the real dataclasses without
# requiring a live rclpy backend.
# ---------------------------------------------------------------------------


def _topic(name: str, ty: str, pubs: int = 1, subs: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        name=name, types=(ty,), primary_type=ty, publisher_count=pubs, subscriber_count=subs
    )


def _node(fqn: str) -> SimpleNamespace:
    name = fqn.rsplit("/", 1)[-1]
    ns = fqn.rsplit("/", 1)[0] or "/"
    return SimpleNamespace(name=name, fqn=fqn, namespace=ns)


def _service(name: str, ty: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, types=(ty,), primary_type=ty)


def _action(name: str, ty: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, types=(ty,), primary_type=ty)


TOPICS = [
    _topic("/odom", "nav_msgs/msg/Odometry", pubs=1, subs=1),
    _topic("/scan", "sensor_msgs/msg/LaserScan", pubs=1, subs=0),
    _topic("/tf", "tf2_msgs/msg/TFMessage", pubs=2, subs=0),
    _topic("/tf_static", "tf2_msgs/msg/TFMessage", pubs=2, subs=0),
    _topic("/cmd_vel", "geometry_msgs/msg/Twist", pubs=1, subs=1),
    _topic("/joint_states", "sensor_msgs/msg/JointState", pubs=1, subs=2),
    _topic("/imu/data", "sensor_msgs/msg/Imu", pubs=1, subs=0),
    _topic("/camera/image_raw", "sensor_msgs/msg/Image", pubs=1, subs=0),
    _topic("/rosout", "rcl_interfaces/msg/Log", pubs=4, subs=1),
    _topic("/parameter_events", "rcl_interfaces/msg/ParameterEvent", pubs=4, subs=4),
]

NODES = [
    _node("/odom_publisher"),
    _node("/scan_publisher"),
    _node("/joint_state_broadcaster"),
    _node("/controller/cmd_vel_mux"),
    _node("/teleop_keyboard"),
    _node("/transform_listener_impl_xyz"),
]

SERVICES = [
    _service("/controller/load_controller", "controller_manager_msgs/srv/LoadController"),
    _service("/controller/list_controllers", "controller_manager_msgs/srv/ListControllers"),
    _service("/get_parameters", "rcl_interfaces/srv/GetParameters"),
    _service("/set_parameters", "rcl_interfaces/srv/SetParameters"),
    _service("/list_parameters", "rcl_interfaces/srv/ListParameters"),
    _service("/describe_parameters", "rcl_interfaces/srv/DescribeParameters"),
]

ACTIONS = [
    _action("/navigate_to_pose", "nav2_msgs/action/NavigateToPose"),
    _action("/follow_path", "nav2_msgs/action/FollowPath"),
    _action("/compute_path_to_pose", "nav2_msgs/action/ComputePathToPose"),
]


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


async def _capture(app: RosightApp, pilot: Any, tab_id: str, out_name: str) -> None:
    """Switch to ``tab_id``, let layout settle, and save ``out_name``.svg."""
    pilot.app.query_one(TabbedContent).active = tab_id
    for _ in range(6):
        await pilot.pause()
    await asyncio.sleep(0.05)
    saved = app.save_screenshot(filename=f"{out_name}.svg", path=str(OUT))
    print(f"  saved {saved}")


async def _stub_topics(app: RosightApp, pilot: Any) -> None:
    from rosight.widgets.topics_panel import TopicsPanel

    panel = app.query_one(TopicsPanel)
    panel._topic_cache = TOPICS
    panel.selected_topic = "/odom"
    panel._render_table()
    await pilot.pause()
    # Populate the info area so the screenshot shows what `i` produces.
    panel.action_info()
    # Also fill a fake live header to show off the realtime line.
    try:
        header = app.query_one("#detail-header", Static)
        header.update(
            "/odom\ntype: nav_msgs/msg/Odometry   hz: 49.8 Hz   bw: 31.2 KB/s   jitter: 0.3ms"
        )
    except Exception:
        pass
    await pilot.pause()


async def _stub_nodes(app: RosightApp, pilot: Any) -> None:
    from rosight.widgets.nodes_panel import NodesPanel

    panel = app.query_one(NodesPanel)
    panel._node_cache = NODES
    panel._render_table()
    await pilot.pause()


async def _stub_services(app: RosightApp, pilot: Any) -> None:
    from rosight.widgets.services_panel import ServicesPanel

    panel = app.query_one(ServicesPanel)
    panel._svc_cache = SERVICES
    panel._render_table()
    await pilot.pause()


async def _stub_actions(app: RosightApp, pilot: Any) -> None:
    from rosight.widgets.actions_panel import ActionsPanel

    panel = app.query_one(ActionsPanel)
    panel._action_cache = ACTIONS
    panel._render_table()
    await pilot.pause()


async def _stub_plot(app: RosightApp, pilot: Any) -> None:
    """Capture the empty Plot tab — that's the "no series" screen most users
    see first and it's where the workflow question starts.

    We tried injecting fake series via PlotView.add_series + push, but
    plotext's legend builder indexes a tiny render region and crashes on
    the headless terminal we use here. Falling back to empty state is
    actually the more honest screenshot for the docs.
    """
    await pilot.pause()


async def _stub_bags(app: RosightApp, pilot: Any) -> None:
    """No subprocess — just flip the header into 'recording' state for the shot."""
    from rosight.widgets.bags_panel import BagsPanel

    panel = app.query_one(BagsPanel)
    panel._set_recording(True)
    await pilot.pause()


async def main() -> None:
    app = RosightApp(ros=RosBackend())  # no_ros, never started
    async with app.run_test(headless=True, size=(140, 38)) as pilot:
        for _ in range(4):
            await pilot.pause()

        plan = [
            ("topics", "01-messages", _stub_topics),
            ("nodes", "02-nodes", _stub_nodes),
            ("services", "03-services", _stub_services),
            ("actions", "04-actions", _stub_actions),
            ("plot", "05-plot", _stub_plot),
            ("bags", "06-bags", _stub_bags),
            ("interfaces", "07-interfaces", None),
        ]
        for tab_id, out_name, stub in plan:
            pilot.app.query_one(TabbedContent).active = tab_id
            for _ in range(6):
                await pilot.pause()
            if stub is not None:
                await stub(app, pilot)
            await _capture(app, pilot, tab_id, out_name)


if __name__ == "__main__":
    asyncio.run(main())
