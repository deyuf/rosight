"""Generate the documentation screenshots (SVG + PNG) of every Rosight view.

Why this exists:
    Most contributors don't have a ROS graph with odometry, a laser and a
    nav2 stack at hand. This script runs the real app under Textual's pilot
    harness against an in-process *demo backend* — real ``Subscription``
    objects fed with synthetic rates and nested fake ROS messages — drives
    each feature (subscribe, plot, service call, action goal, parameters,
    forms, palette completion) and saves one SVG per view into
    ``docs/screenshots/``. PNGs (1600 px wide, for the README / PyPI page)
    are rendered from the SVGs with headless Chromium via Playwright when it
    is installed; pass ``--svg-only`` to skip that.

Run with:
    python scripts/generate_screenshots.py [--svg-only]
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# Keep the user's real ~/.config/rosight (theme, saved UI state) out of it.
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="rosight-shots-")
# plotext caps chart width at the terminal size, which is 80x24 when not
# attached to a tty; make room for the full plot pane.
os.environ.setdefault("COLUMNS", "220")
os.environ.setdefault("LINES", "60")

from textual.widgets import TextArea, Tree

from rosight.app import RosightApp
from rosight.ros import introspection
from rosight.ros.backend import (
    ActionInfo,
    NodeInfo,
    ParameterValue,
    RosBackend,
    ServiceInfo,
    Subscription,
    TopicInfo,
)
from rosight.ros.discovery import GraphSnapshot
from rosight.widgets.message_tree import MessageTree

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
SIZE = (150, 42)
PNG_WIDTH = 1600


# ---------------------------------------------------------------------------
# Fake ROS message types: nested classes that quack like rosidl messages
# (``get_fields_and_field_types`` + ``pkg/Type`` naming).
# ---------------------------------------------------------------------------

_PRIMITIVE_DEFAULTS = {
    "float64": 0.0,
    "float32": 0.0,
    "int32": 0,
    "uint32": 0,
    "int64": 0,
    "string": "",
    "boolean": False,
}
TYPES: dict[str, type] = {}


def msg_type(full_name: str, fields: dict[str, str]) -> type:
    pkg, _, name = full_name.split("/")

    def __init__(self: Any, **kw: Any) -> None:
        for f, t in fields.items():
            if f in kw:
                setattr(self, f, kw[f])
            elif t in _PRIMITIVE_DEFAULTS:
                setattr(self, f, _PRIMITIVE_DEFAULTS[t])
            elif "[" in t or t.startswith("sequence<"):
                setattr(self, f, [0.0] * int(t.split("[")[1].rstrip("]") or 0) if "[" in t else [])
            else:
                setattr(self, f, TYPES[t]())

    cls = type(
        name,
        (),
        {"__init__": __init__, "get_fields_and_field_types": staticmethod(lambda: dict(fields))},
    )
    cls.__module__ = f"{pkg}.{_}"
    TYPES[full_name] = cls
    TYPES[f"{pkg}/{name}"] = cls
    return cls


Time = msg_type("builtin_interfaces/msg/Time", {"sec": "int32", "nanosec": "uint32"})
Header = msg_type(
    "std_msgs/msg/Header", {"stamp": "builtin_interfaces/msg/Time", "frame_id": "string"}
)
Point = msg_type("geometry_msgs/msg/Point", {"x": "float64", "y": "float64", "z": "float64"})
Vector3 = msg_type("geometry_msgs/msg/Vector3", {"x": "float64", "y": "float64", "z": "float64"})
Quaternion = msg_type(
    "geometry_msgs/msg/Quaternion", {"x": "float64", "y": "float64", "z": "float64", "w": "float64"}
)
Pose = msg_type(
    "geometry_msgs/msg/Pose",
    {"position": "geometry_msgs/msg/Point", "orientation": "geometry_msgs/msg/Quaternion"},
)
Twist = msg_type(
    "geometry_msgs/msg/Twist",
    {"linear": "geometry_msgs/msg/Vector3", "angular": "geometry_msgs/msg/Vector3"},
)
PoseCov = msg_type(
    "geometry_msgs/msg/PoseWithCovariance",
    {"pose": "geometry_msgs/msg/Pose", "covariance": "double[36]"},
)
TwistCov = msg_type(
    "geometry_msgs/msg/TwistWithCovariance",
    {"twist": "geometry_msgs/msg/Twist", "covariance": "double[36]"},
)
Odometry = msg_type(
    "nav_msgs/msg/Odometry",
    {
        "header": "std_msgs/msg/Header",
        "child_frame_id": "string",
        "pose": "geometry_msgs/msg/PoseWithCovariance",
        "twist": "geometry_msgs/msg/TwistWithCovariance",
    },
)
LaserScan = msg_type(
    "sensor_msgs/msg/LaserScan",
    {
        "header": "std_msgs/msg/Header",
        "angle_min": "float32",
        "angle_max": "float32",
        "range_min": "float32",
        "range_max": "float32",
        "ranges": "sequence<float32>",
    },
)
JointState = msg_type(
    "sensor_msgs/msg/JointState",
    {
        "header": "std_msgs/msg/Header",
        "name": "sequence<string>",
        "position": "sequence<float64>",
        "velocity": "sequence<float64>",
    },
)
AddTwoIntsRequest = msg_type(
    "example_interfaces/srv/AddTwoInts_Request", {"a": "int64", "b": "int64"}
)
AddTwoIntsResponse = msg_type("example_interfaces/srv/AddTwoInts_Response", {"sum": "int64"})
NavFeedback = msg_type(
    "nav2_msgs/action/NavigateToPose_Feedback",
    {
        "current_pose": "geometry_msgs/msg/Pose",
        "distance_remaining": "float32",
        "number_of_recoveries": "int32",
    },
)


def odom(t: float) -> Any:
    m = Odometry()
    m.header.stamp.sec, m.header.frame_id, m.child_frame_id = (
        1731400000 + int(t),
        "odom",
        "base_link",
    )
    m.pose.pose.position.x = round(2.0 + 1.5 * math.cos(t / 4), 4)
    m.pose.pose.position.y = round(1.5 * math.sin(t / 4), 4)
    m.pose.pose.orientation.z, m.pose.pose.orientation.w = (
        round(math.sin(t / 8), 4),
        round(math.cos(t / 8), 4),
    )
    m.twist.twist.linear.x = round(0.4 + 0.1 * math.sin(t), 4)
    m.twist.twist.angular.z = round(0.25 * math.cos(t / 2), 4)
    return m


def scan(t: float) -> Any:
    return LaserScan(
        angle_min=-2.35,
        angle_max=2.35,
        range_min=0.1,
        range_max=12.0,
        ranges=[
            round(2.5 + 1.2 * math.sin(i / 9 + t) + 0.3 * math.cos(i / 3), 3) for i in range(180)
        ],
    )


def joints(t: float) -> Any:
    names = ["shoulder", "elbow", "wrist_1", "wrist_2", "gripper"]
    return JointState(
        name=names,
        position=[round(math.sin(t + i), 3) for i in range(5)],
        velocity=[round(math.cos(t + i) / 2, 3) for i in range(5)],
    )


# ---------------------------------------------------------------------------
# Demo backend
# ---------------------------------------------------------------------------

TOPICS = (
    TopicInfo("/odom", ("nav_msgs/msg/Odometry",), 1, 2),
    TopicInfo("/scan", ("sensor_msgs/msg/LaserScan",), 1, 1),
    TopicInfo("/joint_states", ("sensor_msgs/msg/JointState",), 1, 2),
    TopicInfo("/cmd_vel", ("geometry_msgs/msg/Twist",), 1, 1),
    TopicInfo("/tf", ("tf2_msgs/msg/TFMessage",), 2, 3),
    TopicInfo("/tf_static", ("tf2_msgs/msg/TFMessage",), 2, 3),
    TopicInfo("/imu/data", ("sensor_msgs/msg/Imu",), 1, 0),
    TopicInfo("/camera/image_raw", ("sensor_msgs/msg/Image",), 1, 0),
    TopicInfo("/map", ("nav_msgs/msg/OccupancyGrid",), 1, 1),
    TopicInfo("/rosout", ("rcl_interfaces/msg/Log",), 6, 1),
    TopicInfo("/parameter_events", ("rcl_interfaces/msg/ParameterEvent",), 6, 6),
)
NODES = (
    NodeInfo("controller_server", "/"),
    NodeInfo("cmd_vel_mux", "/controller"),
    NodeInfo("joint_state_broadcaster", "/"),
    NodeInfo("planner_server", "/"),
    NodeInfo("robot_state_publisher", "/"),
    NodeInfo("lidar_driver", "/sensors"),
    NodeInfo("rosight", "/"),
)
SERVICES = (
    ServiceInfo("/add_two_ints", ("example_interfaces/srv/AddTwoInts",)),
    ServiceInfo("/controller/list_controllers", ("controller_manager_msgs/srv/ListControllers",)),
    ServiceInfo("/controller/load_controller", ("controller_manager_msgs/srv/LoadController",)),
    ServiceInfo("/planner_server/get_parameters", ("rcl_interfaces/srv/GetParameters",)),
    ServiceInfo("/planner_server/set_parameters", ("rcl_interfaces/srv/SetParameters",)),
)
ACTIONS = (
    ActionInfo("/navigate_to_pose", ("nav2_msgs/action/NavigateToPose",)),
    ActionInfo("/follow_path", ("nav2_msgs/action/FollowPath",)),
    ActionInfo("/compute_path_to_pose", ("nav2_msgs/action/ComputePathToPose",)),
)
PARAMS = [
    ParameterValue("controller_frequency", "double", 20.0),
    ParameterValue("max_linear_vel", "double", 0.6),
    ParameterValue("max_angular_vel", "double", 1.2),
    ParameterValue("use_sim_time", "bool", False),
    ParameterValue("odom_topic", "string", "/odom"),
    ParameterValue("plugins", "string_array", ["FollowPath", "Recovery"]),
    ParameterValue("speed_limit_topic", "string", "speed_limit"),
]


class DemoRos:
    started = True
    executor_alive = True
    last_error = None
    domain_id = 0

    def __init__(self) -> None:
        self.subs: dict[str, Subscription] = {}
        self.snap = GraphSnapshot(TOPICS, NODES, SERVICES, ACTIONS, generation=1)
        self.goal_release = threading.Event()

    # discovery
    def graph_snapshot(self) -> GraphSnapshot:
        return self.snap

    def request_graph_refresh(self) -> None:
        pass

    def list_topics(self) -> list:
        return list(TOPICS)

    def publisher_qos(self, _t: str) -> list:
        return []

    def node_info(self, fqn: str) -> dict:
        return {
            "publishers": [
                ("/cmd_vel", ("geometry_msgs/msg/Twist",)),
                ("/rosout", ("rcl_interfaces/msg/Log",)),
            ],
            "subscribers": [
                ("/odom", ("nav_msgs/msg/Odometry",)),
                ("/scan", ("sensor_msgs/msg/LaserScan",)),
                ("/parameter_events", ("rcl_interfaces/msg/ParameterEvent",)),
            ],
            "service_servers": [
                (f"{fqn}/get_parameters", ("rcl_interfaces/srv/GetParameters",)),
                (f"{fqn}/set_parameters", ("rcl_interfaces/srv/SetParameters",)),
            ],
            "service_clients": [
                ("/controller/list_controllers", ("controller_manager_msgs/srv/ListControllers",))
            ],
        }

    # subscriptions
    def active_subscriptions(self) -> list:
        return list(self.subs.values())

    def get_subscription(self, topic: str) -> Subscription | None:
        return self.subs.get(topic)

    def subscribe(self, topic: str, type_name: str | None = None, **_kw: Any) -> Subscription:
        if topic not in self.subs:
            ti = next(t for t in TOPICS if t.name == topic)
            self.subs[topic] = Subscription(topic, type_name or ti.primary_type)
        return self.subs[topic]

    def unsubscribe(self, topic: str) -> None:
        self.subs.pop(topic, None)

    def feed(self, topic: str, make: Any, hz: float, size: int) -> None:
        """Fill a subscription with 5 s of history at ``hz``."""
        sub = self.subscribe(topic)
        now = time.monotonic()
        n = int(hz * 4.9)
        for i in range(n):
            ts = now - 4.9 + i / hz + (0.0004 if i % 3 else -0.0003)
            sub.rate.tick(ts)
            sub.bandwidth.tick(size, ts)
        sub._set_latest(make(now), now)

    # services / params / actions
    def call_service(self, _name: str, _type: str, req: Any) -> Any:
        return AddTwoIntsResponse(sum=req.a + req.b)

    def list_parameters(self, _node: str) -> list[str]:
        return [p.name for p in PARAMS]

    def get_parameters(self, _node: str, _names: list[str]) -> list:
        return list(PARAMS)

    def run_action_goal(
        self, _name: str, _type: str, _goal: Any, *, on_feedback: Any, on_accepted: Any, cancel: Any
    ) -> tuple[int, Any]:
        on_accepted()
        fb = NavFeedback(distance_remaining=3.42, number_of_recoveries=0)
        fb.current_pose.position.x, fb.current_pose.position.y = 1.23, -0.48
        fb.current_pose.orientation.w = 1.0
        on_feedback(fb)
        self.goal_release.wait(30)
        return 4, SimpleNamespace(get_fields_and_field_types=lambda: {})

    def stop(self) -> None:
        pass


def _patch_introspection() -> Any:
    """Point type lookup at the demo types; returns a function that undoes
    it (this module is also imported by tests, which must not leak fakes
    into later tests that use real ROS types)."""
    saved = (introspection.get_message_class, introspection.get_service_class)
    introspection.get_message_class = lambda t: TYPES[t]  # type: ignore[assignment]
    introspection.get_service_class = lambda t: SimpleNamespace(  # type: ignore[assignment]
        Request=TYPES[t + "_Request"]
    )

    def restore() -> None:
        introspection.get_message_class, introspection.get_service_class = saved

    return restore


# ---------------------------------------------------------------------------
# Scenes
# ---------------------------------------------------------------------------


async def settle(pilot: Any, n: int = 6) -> None:
    for _ in range(n):
        await pilot.pause()


async def show_tab(pilot: Any, tab: str) -> None:
    pilot.app.action_tab(tab)  # same path as pressing 1-9
    await settle(pilot)


def save(app: RosightApp, name: str) -> Path:
    path = Path(app.save_screenshot(filename=f"{name}.svg", path=str(OUT)))
    print(f"  saved {path.name}")
    return path


async def scene_messages(app: RosightApp, pilot: Any, ros: DemoRos) -> None:
    from rosight.widgets.topics_panel import TopicsPanel

    await show_tab(pilot, "topics")
    panel = app.query_one(TopicsPanel)
    trend = {
        "/odom": [49.9, 50.0, 50.1, 49.8, 50.0, 50.0, 49.9, 50.0],
        "/scan": [9.8, 10.0, 9.9, 6.2, 3.1, 9.7, 10.0, 9.9],
        "/joint_states": [100.0] * 8,
        "/cmd_vel": [0.0, 0.0, 20.0, 20.0, 19.9, 20.0, 20.0, 20.1],
    }
    for topic, hist in trend.items():
        panel._hz_hist[topic] = deque(hist, maxlen=8)
    panel._refresh_table()
    panel.focus_topic("/odom")
    await settle(pilot)
    tree = app.query_one("#msg-tree", MessageTree)
    MessageTree.FLASH_SECONDS = 30  # keep the change highlight visible for the shot
    panel._refresh_detail()
    await settle(pilot)
    for path in ("pose.covariance", "twist.covariance", "header", "pose.pose.orientation"):
        node = tree._nodes_by_path.get(path)
        if node is not None:
            node.collapse()
    for path in ("twist.twist.linear", "twist.twist.angular"):
        tree._nodes_by_path[path].expand()
    await settle(pilot)
    sub = ros.subs["/odom"]
    sub._set_latest(odom(time.monotonic() + 0.7), time.monotonic())
    panel._refresh_detail()  # values change → flash
    tree.focus()
    await settle(pilot)
    tree.move_cursor(tree._nodes_by_path["twist.twist.linear.x"])
    await settle(pilot)
    save(app, "01-messages")


async def scene_nodes(app: RosightApp, pilot: Any, ros: DemoRos) -> None:
    from rosight.widgets.nodes_panel import NodesPanel

    await show_tab(pilot, "nodes")
    panel = app.query_one(NodesPanel)
    panel.focus_item("/controller/cmd_vel_mux")
    await settle(pilot)
    tree = panel.query_one("#node-detail", Tree)
    tree.focus()
    tree.move_cursor(tree.root.children[1].children[0])  # subscriber /odom
    await settle(pilot)
    save(app, "02-nodes")


async def scene_services(app: RosightApp, pilot: Any, ros: DemoRos) -> None:
    from rosight.widgets.services_panel import ServicesPanel

    await show_tab(pilot, "services")
    panel = app.query_one(ServicesPanel)
    panel.focus_item("/add_two_ints")
    await settle(pilot)
    await panel._call(
        "/add_two_ints", "example_interfaces/srv/AddTwoInts", AddTwoIntsRequest(a=2, b=40)
    )
    await settle(pilot)
    save(app, "03-services")


async def scene_actions(app: RosightApp, pilot: Any, ros: DemoRos) -> None:
    from rosight.widgets.actions_panel import ActionsPanel

    await show_tab(pilot, "actions")
    panel = app.query_one(ActionsPanel)
    panel.focus_item("/navigate_to_pose")
    await settle(pilot)
    panel.run_worker(
        panel._run_goal("/navigate_to_pose", "nav2_msgs/action/NavigateToPose", object()),
        group="goal",
    )
    for _ in range(40):
        await pilot.pause()
        if "feedback" in str(panel.query_one("#act-detail").render()):
            break
    await settle(pilot)
    save(app, "04-actions")
    ros.goal_release.set()
    await settle(pilot)


async def scene_plot(app: RosightApp, pilot: Any, ros: DemoRos) -> None:
    from rosight.widgets.plot_panel import PlotPanel

    panel = app.query_one(PlotPanel)
    panel.add_series("/odom", "twist.twist.linear.x")
    panel.add_series("/odom", "twist.twist.angular.z")
    panel.add_snapshot_series("/scan", "ranges")
    now = time.monotonic()
    for i in range(600):
        t = now - 30 + i * 0.05
        m = odom(t)
        panel.plot.push("/odom/twist.twist.linear.x", m.twist.twist.linear.x, t)
        panel.plot.push("/odom/twist.twist.angular.z", m.twist.twist.angular.z, t)
    panel.plot.push_snapshot("/scan/ranges", scan(now).ranges, now)
    await show_tab(pilot, "plot")
    panel._refresh_table()
    await settle(pilot, 10)
    save(app, "05-plot")


async def scene_bags(app: RosightApp, pilot: Any, ros: DemoRos) -> None:
    from rosight.widgets.bags_panel import BagsPanel

    await show_tab(pilot, "bags")
    panel = app.query_one(BagsPanel)
    fake = SimpleNamespace(
        pid=48213,
        returncode=None,
        poll=lambda: None,
        send_signal=lambda _s: None,
        wait=lambda timeout=None: 0,
    )
    panel._record_proc = fake
    panel._set_recording(True)
    panel._refresh()
    await settle(pilot)
    save(app, "06-bags")
    panel._record_proc = None


async def scene_interfaces(app: RosightApp, pilot: Any, ros: DemoRos) -> None:
    from rosight.widgets.interfaces_panel import InterfacesPanel

    await show_tab(pilot, "interfaces")
    panel = app.query_one(InterfacesPanel)
    names = {
        n
        for n in TYPES
        if n.count("/") == 2 and not n.endswith(("_Request", "_Response", "_Feedback"))
    }
    # Real systems have much longer names than the demo types; keep a few so
    # the layout check sees them (CI's ROS images list hundreds like these).
    names |= {
        "composition_interfaces/srv/LoadNode_Response",
        "rcl_interfaces/msg/ParameterEventDescriptors",
        "rosbag2_interfaces/srv/SetRate_Response",
    }
    panel._cache = sorted((n, n.split("/")[1]) for n in names)
    panel._render_table()
    keys = [k for k, _ in panel._cache]
    table = panel.query_one("#iface-table")
    table.focus()
    table.move_cursor(row=keys.index("nav_msgs/msg/Odometry"))
    await settle(pilot)
    save(app, "07-interfaces")


async def scene_params(app: RosightApp, pilot: Any, ros: DemoRos) -> None:
    from rosight.widgets.params_panel import ParamsPanel

    await show_tab(pilot, "params")
    panel = app.query_one(ParamsPanel)
    panel._refresh_nodes()
    await settle(pilot)
    panel.open_node("/controller_server")
    await settle(pilot, 10)
    table = panel.query_one("#params-table")
    table.focus()
    table.move_cursor(row=1)
    await settle(pilot)
    save(app, "08-params")


async def scene_publish_form(app: RosightApp, pilot: Any, ros: DemoRos) -> None:
    from rosight.widgets.topics_panel import TopicsPanel

    await show_tab(pilot, "topics")
    panel = app.query_one(TopicsPanel)
    panel.focus_topic("/cmd_vel")
    await settle(pilot)
    panel.action_publish()
    await settle(pilot)
    area = app.screen.query_one(TextArea)
    area.text = "linear:\n  x: 0.3\n  y: 0.0\n  z: 0.0\nangular:\n  x: 0.0\n  y: 0.0\n  z: 0.5\n"
    await settle(pilot)
    save(app, "09-publish-form")
    await pilot.press("escape")
    await settle(pilot)


async def scene_palette(app: RosightApp, pilot: Any, ros: DemoRos) -> None:
    app.action_command()
    await settle(pilot)
    await pilot.press(*"plot /odom twist.twist.lin")
    await settle(pilot)
    save(app, "10-command-palette")
    await pilot.press("escape")
    await settle(pilot)


SCENES = [
    scene_messages,
    scene_nodes,
    scene_services,
    scene_actions,
    scene_plot,
    scene_bags,
    scene_interfaces,
    scene_params,
    scene_publish_form,
    scene_palette,
]


async def capture_all(size: tuple[int, int] = SIZE) -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    restore = _patch_introspection()
    try:
        ros = DemoRos()
        ros.feed("/odom", odom, hz=50, size=726)
        ros.feed("/scan", scan, hz=10, size=1484)
        ros.feed("/joint_states", joints, hz=100, size=312)
        ros.feed("/cmd_vel", lambda _t: Twist(), hz=20, size=48)
        app = RosightApp(ros=RosBackend())
        async with app.run_test(headless=True, size=size) as pilot:
            app.ros = ros  # type: ignore[assignment]
            app.backend_ok = True
            app._refresh_status()
            await settle(pilot)
            for scene in SCENES:
                app._refresh_status()
                await scene(app, pilot, ros)
    finally:
        restore()
    return sorted(OUT.glob("*.svg"))


def render_pngs(svgs: list[Path]) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed — skipping PNG rendering")
        return
    import re

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for svg in svgs:
            text = svg.read_text(encoding="utf-8")
            m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', text)
            w, h = (float(m.group(1)), float(m.group(2))) if m else (1600.0, 900.0)
            height = round(PNG_WIDTH * h / w)
            page = browser.new_page(viewport={"width": PNG_WIDTH, "height": height})
            page.set_content(
                f'<html><body style="margin:0;background:#0c0c0c">'
                f'<img src="{svg.as_uri()}" style="width:{PNG_WIDTH}px;display:block"></body></html>'
            )
            page.wait_for_timeout(300)
            page.screenshot(path=str(svg.with_suffix(".png")), full_page=True)
            page.close()
            print(f"  rendered {svg.with_suffix('.png').name}")
        browser.close()


def main() -> None:
    global OUT  # noqa: PLW0603 — scenes write to the module-level output dir
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--svg-only", action="store_true", help="don't render PNGs")
    ap.add_argument("--size", default=f"{SIZE[0]}x{SIZE[1]}", help="terminal COLSxROWS")
    ap.add_argument("--out", type=Path, default=OUT, help="output directory")
    args = ap.parse_args()
    OUT = args.out
    cols, rows = (int(v) for v in args.size.lower().split("x"))
    svgs = asyncio.run(capture_all((cols, rows)))
    if not args.svg_only:
        render_pngs(svgs)


if __name__ == "__main__":
    main()
