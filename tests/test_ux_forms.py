"""YAML forms: converters, the modal, publish / call / goal / param flows."""

from __future__ import annotations

import array
import sys
import threading
import types
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Static, TabbedContent, TextArea

from rosight.app import RosightApp
from rosight.ros import introspection
from rosight.ros.backend import ActionInfo, ParameterValue, RosBackend, ServiceInfo, TopicInfo
from rosight.ros.discovery import GraphSnapshot
from rosight.ros.yaml_msg import MessageYamlError, message_to_yaml, to_plain, yaml_to_message
from rosight.widgets.yaml_form import YamlFormScreen

# ----- fake message types ------------------------------------------------------


class Vec:
    def __init__(self):
        self.x = 0.0
        self.y = 0.0

    @staticmethod
    def get_fields_and_field_types():
        return {"x": "float64", "y": "float64"}


class Twist:
    def __init__(self):
        self.linear = Vec()
        self.angular = Vec()

    @staticmethod
    def get_fields_and_field_types():
        return {"linear": "geometry_msgs/Vector3", "angular": "geometry_msgs/Vector3"}


class AddTwoInts:
    class Request:
        def __init__(self):
            self.a = 0
            self.b = 0

        @staticmethod
        def get_fields_and_field_types():
            return {"a": "int64", "b": "int64"}


class Labelled:
    def __init__(self):
        self.name = ""
        self.enabled = False
        self.values = array.array("d", [1.0, 2.0])
        self.raw = b"\x01\x02"

    @staticmethod
    def get_fields_and_field_types():
        return {
            "name": "string",
            "enabled": "boolean",
            "values": "sequence<double>",
            "raw": "sequence<uint8>",
        }


# ----- converters ----------------------------------------------------------------


def test_to_plain_handles_arrays_bytes_and_nesting():
    assert to_plain(Labelled()) == {
        "name": "",
        "enabled": False,
        "values": [1.0, 2.0],
        "raw": [1, 2],
    }

    class FakeNdarray:
        def tolist(self):
            return [[1, 0], [0, 1]]

    assert to_plain([FakeNdarray()]) == [[[1, 0], [0, 1]]]


def test_round_trip_nested_message():
    t = Twist()
    t.linear.x = 0.5
    text = message_to_yaml(t)
    assert text.splitlines()[0] == "linear:"
    back = yaml_to_message(text, Twist)
    assert back.linear.x == 0.5 and back.angular.y == 0.0


def test_yaml_to_message_partial_and_coercion():
    msg = yaml_to_message("linear: {x: 1}", Twist)
    assert msg.linear.x == 1.0 and isinstance(msg.linear.x, float)
    assert yaml_to_message("", Twist).linear.x == 0.0


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("linear: {z: 1}", "unknown field 'linear.z'"),
        ("linear: {x: fast}", "expects a number"),
        ("linear: 3", "nested message"),
        ("- 1\n- 2", "mapping"),
        ("linear: {x: [1,", "invalid YAML"),
    ],
)
def test_yaml_to_message_errors(text, match):
    with pytest.raises(MessageYamlError, match=match):
        yaml_to_message(text, Twist)


def test_yaml_to_message_type_checks_scalars():
    with pytest.raises(MessageYamlError, match="true/false"):
        yaml_to_message("enabled: 1", Labelled)
    with pytest.raises(MessageYamlError, match="string"):
        yaml_to_message("name: 5", Labelled)
    with pytest.raises(MessageYamlError, match="list"):
        yaml_to_message("values: 5", Labelled)
    msg = yaml_to_message("name: hi\nvalues: [3, 4]", Labelled)
    assert msg.name == "hi" and msg.values == [3, 4]


# ----- YamlFormScreen --------------------------------------------------------------


@pytest.mark.asyncio
async def test_form_validates_inline_then_submits():
    results: list = []
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(140, 40)) as pilot:

        def validate(t: str):
            return None if "ok" in t else "needs ok"

        pilot.app.push_screen(YamlFormScreen("T", "bad", validate=validate), results.append)
        await pilot.pause()
        await pilot.press("ctrl+s")
        await pilot.pause()
        screen = pilot.app.screen
        assert isinstance(screen, YamlFormScreen), "invalid input keeps the form open"
        assert "needs ok" in str(screen.query_one("#form-error", Static).render())
        screen.query_one(TextArea).text = "ok"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert results == ["ok"]

        pilot.app.push_screen(YamlFormScreen("T", "x"), results.append)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert results == ["ok", None]


# ----- panel flows ------------------------------------------------------------------


class _Ros:
    def __init__(self, snap: GraphSnapshot):
        self.started = True
        self.executor_alive = True
        self.domain_id = 0
        self.snap = snap
        self.published: list = []
        self.calls: list = []
        self.param_sets: list = []
        self.params = [
            ParameterValue("max_speed", "double", 1.5),
            ParameterValue("frame", "string", "map"),
        ]
        self.goal_release = threading.Event()

    def graph_snapshot(self):
        return self.snap

    def active_subscriptions(self):
        return []

    def get_subscription(self, _t):
        return None

    def publish_once(self, topic, type_name, msg):
        self.published.append((topic, type_name, msg))

    def call_service(self, name, type_name, req):
        self.calls.append((name, req))
        return SimpleNamespace(
            sum=req.a + req.b, get_fields_and_field_types=lambda: {"sum": "int64"}
        )

    def list_parameters(self, _node):
        return [p.name for p in self.params]

    def get_parameters(self, _node, _names):
        return list(self.params)

    def set_parameter(self, node, name, value, type_hint=None):
        self.param_sets.append((node, name, value, type_hint))
        return True

    def run_action_goal(self, name, type_name, goal, *, on_feedback, on_accepted, cancel):
        on_accepted()
        on_feedback(
            SimpleNamespace(progress=0.5, get_fields_and_field_types=lambda: {"progress": "float"})
        )
        if not self.goal_release.wait(0.05):
            cancel.wait(5)
            return 5, SimpleNamespace(get_fields_and_field_types=lambda: {})
        return 4, SimpleNamespace(done=True, get_fields_and_field_types=lambda: {"done": "bool"})

    def stop(self):
        pass


async def _settle(pilot, n=4):
    for _ in range(n):
        await pilot.pause()


@pytest.mark.asyncio
async def test_publish_form_publishes_edited_message(monkeypatch):
    from rosight.widgets.topics_panel import TopicsPanel

    monkeypatch.setattr(introspection, "get_message_class", lambda _t: Twist)
    ros = _Ros(
        GraphSnapshot(topics=(TopicInfo("/cmd_vel", ("geometry_msgs/msg/Twist",)),), generation=1)
    )
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        pilot.app.query_one(TabbedContent).active = "topics"
        await _settle(pilot)
        panel = pilot.app.query_one(TopicsPanel)
        panel._refresh_table()
        panel.selected_topic = "/cmd_vel"
        panel.action_publish()
        await _settle(pilot)
        form = pilot.app.screen
        assert isinstance(form, YamlFormScreen)
        assert "linear:" in form.query_one(TextArea).text
        form.query_one(TextArea).text = "linear: {x: 0.3}\nangular: {z: 0}".replace("z", "y")
        await pilot.press("ctrl+s")
        await _settle(pilot, 8)
    ((topic, _type_name, msg),) = ros.published
    assert topic == "/cmd_vel" and msg.linear.x == 0.3


@pytest.mark.asyncio
async def test_service_call_shows_response_and_remembers_request(monkeypatch):
    from rosight.widgets.services_panel import ServicesPanel

    monkeypatch.setattr(introspection, "get_service_class", lambda _t: AddTwoInts)
    ros = _Ros(GraphSnapshot(services=(ServiceInfo("/add", ("ex/srv/AddTwoInts",)),), generation=1))
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        pilot.app.query_one(TabbedContent).active = "services"
        await _settle(pilot)
        panel = pilot.app.query_one(ServicesPanel)
        panel._refresh(force=True)
        panel.selected = "/add"
        panel.action_call()
        await _settle(pilot)
        pilot.app.screen.query_one(TextArea).text = "a: 2\nb: 40"
        await pilot.press("ctrl+s")
        await _settle(pilot, 8)
        detail = str(pilot.app.query_one("#srv-detail", Static).render())
        assert "sum: 42" in detail
        panel.action_call()
        await _settle(pilot)
        assert pilot.app.screen.query_one(TextArea).text == "a: 2\nb: 40"


@pytest.mark.asyncio
async def test_action_goal_runs_with_feedback_and_result():
    from rosight.ros import introspection as intro
    from rosight.widgets.actions_panel import ActionsPanel

    class Fib:
        class Goal:
            def __init__(self):
                self.order = 0

            @staticmethod
            def get_fields_and_field_types():
                return {"order": "int32"}

    ros = _Ros(GraphSnapshot(actions=(ActionInfo("/fib", ("ex/action/Fibonacci",)),), generation=1))
    ros.goal_release.set()
    orig = intro.get_action_class
    intro.get_action_class = lambda _t: Fib
    try:
        async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
            pilot.app.ros = ros  # type: ignore[assignment]
            pilot.app.query_one(TabbedContent).active = "actions"
            await _settle(pilot)
            panel = pilot.app.query_one(ActionsPanel)
            panel._refresh(force=True)
            panel.selected = "/fib"
            panel.action_send_goal()
            await _settle(pilot)
            pilot.app.screen.query_one(TextArea).text = "order: 5"
            await pilot.press("ctrl+s")
            for _ in range(30):
                await pilot.pause()
                if panel._running_goal is None and "succeeded" in str(
                    pilot.app.query_one("#act-detail", Static).render()
                ):
                    break
            detail = str(pilot.app.query_one("#act-detail", Static).render())
            assert "succeeded" in detail and "done: true" in detail
    finally:
        intro.get_action_class = orig


@pytest.mark.asyncio
async def test_action_goal_cancel():
    from rosight.ros import introspection as intro
    from rosight.widgets.actions_panel import ActionsPanel

    class Fib:
        class Goal:
            def __init__(self):
                self.order = 0

            @staticmethod
            def get_fields_and_field_types():
                return {"order": "int32"}

    ros = _Ros(GraphSnapshot(actions=(ActionInfo("/fib", ("ex/action/Fibonacci",)),), generation=1))
    orig = intro.get_action_class
    intro.get_action_class = lambda _t: Fib
    try:
        async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
            pilot.app.ros = ros  # type: ignore[assignment]
            pilot.app.query_one(TabbedContent).active = "actions"
            await _settle(pilot)
            panel = pilot.app.query_one(ActionsPanel)
            panel._refresh(force=True)
            panel.selected = "/fib"
            panel.action_send_goal()
            await _settle(pilot)
            await pilot.press("ctrl+s")
            for _ in range(20):
                await pilot.pause()
                if panel._running_goal:
                    break
            panel.action_send_goal()  # second goal refused while one runs
            panel.action_cancel_goal()
            for _ in range(40):
                await pilot.pause()
                if panel._running_goal is None:
                    break
            assert "canceled" in str(pilot.app.query_one("#act-detail", Static).render())
    finally:
        intro.get_action_class = orig


@pytest.mark.asyncio
async def test_params_load_set_and_yank():
    from rosight.ros.backend import NodeInfo
    from rosight.widgets.params_panel import ParamsPanel

    ros = _Ros(GraphSnapshot(nodes=(NodeInfo("planner", "/"),), generation=1))
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        copied: list[str] = []
        pilot.app.copy_to_clipboard = copied.append  # type: ignore[method-assign]
        pilot.app.query_one(TabbedContent).active = "params"
        await _settle(pilot)
        panel = pilot.app.query_one(ParamsPanel)
        # NodesPanel uses the same id; query inside the Params panel.
        nodes = panel.query_one("#nodes-table", DataTable)
        for _ in range(20):  # wait until the tab is laid out and populated
            panel._refresh_nodes()
            await pilot.pause()
            if [r.key.value for r in nodes.ordered_rows] == ["/planner"]:
                break
        nodes.focus()
        nodes.move_cursor(row=0)
        await pilot.pause()
        await pilot.press("enter")  # DataTable eats enter → RowSelected → load
        await _settle(pilot, 8)
        params = pilot.app.query_one("#params-table", DataTable)
        assert params.row_count == 2

        params.focus()
        params.move_cursor(row=0)  # max_speed (double)
        await pilot.pause()
        panel.action_set()
        await _settle(pilot)
        form = pilot.app.screen
        assert form.query_one(TextArea).text == "1.5"
        form.query_one(TextArea).text = "fast"
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert isinstance(pilot.app.screen, YamlFormScreen), "type mismatch must be rejected"
        pilot.app.screen.query_one(TextArea).text = "2"
        await pilot.press("ctrl+s")
        await _settle(pilot, 8)
        assert ros.param_sets == [("/planner", "max_speed", 2, "double")]

        panel.action_yank()
        assert "ros__parameters:" in copied[0] and "max_speed: 1.5" in copied[0]


# ----- backend run_action_goal with a fake rclpy.action --------------------------


class _Fut:
    def __init__(self, value=None, ready=True):
        self._value = value
        self._cbs: list = []
        self._ready = ready

    def add_done_callback(self, cb):
        if self._ready:
            cb(self)
        else:
            self._cbs.append(cb)

    def complete(self, value):
        self._value = value
        self._ready = True
        for cb in self._cbs:
            cb(self)

    def result(self):
        return self._value


def _fake_action_module(goal_handle, available=True):
    class FakeClient:
        instances: list = []

        def __init__(self, node, cls, name):
            self.destroyed = False
            FakeClient.instances.append(self)

        def wait_for_server(self, timeout_sec):
            return available

        def send_goal_async(self, goal, feedback_callback=None):
            feedback_callback(SimpleNamespace(feedback="fb1"))
            return _Fut(goal_handle)

        def destroy(self):
            self.destroyed = True

    mod = types.ModuleType("rclpy.action")
    mod.ActionClient = FakeClient
    return mod, FakeClient


@pytest.fixture
def action_backend(monkeypatch):
    monkeypatch.setattr(introspection, "get_action_class", lambda _t: object)
    b = RosBackend()
    b._started = True
    b._node = object()
    return b


def test_run_action_goal_success(action_backend, monkeypatch):
    handle = SimpleNamespace(
        accepted=True,
        get_result_async=lambda: _Fut(SimpleNamespace(status=4, result="R")),
        cancel_goal_async=lambda: None,
    )
    mod, client_cls = _fake_action_module(handle)
    monkeypatch.setitem(sys.modules, "rclpy.action", mod)
    fbs, accepted = [], []
    status, result = action_backend.run_action_goal(
        "/a", "x/action/A", object(), on_feedback=fbs.append, on_accepted=lambda: accepted.append(1)
    )
    assert (status, result) == (4, "R")
    assert fbs == ["fb1"] and accepted == [1]
    assert client_cls.instances[-1].destroyed


def test_run_action_goal_rejected_and_unavailable(action_backend, monkeypatch):
    mod, _ = _fake_action_module(SimpleNamespace(accepted=False))
    monkeypatch.setitem(sys.modules, "rclpy.action", mod)
    with pytest.raises(RuntimeError, match="rejected"):
        action_backend.run_action_goal("/a", "x/action/A", object())
    mod, _ = _fake_action_module(None, available=False)
    monkeypatch.setitem(sys.modules, "rclpy.action", mod)
    with pytest.raises(TimeoutError, match="unavailable"):
        action_backend.run_action_goal("/a", "x/action/A", object(), server_timeout=0.1)


def test_run_action_goal_cancel(action_backend, monkeypatch):
    result_future = _Fut(ready=False)
    cancels: list = []

    def cancel_goal_async():
        cancels.append(1)
        result_future.complete(SimpleNamespace(status=5, result=None))

    handle = SimpleNamespace(
        accepted=True, get_result_async=lambda: result_future, cancel_goal_async=cancel_goal_async
    )
    mod, _ = _fake_action_module(handle)
    monkeypatch.setitem(sys.modules, "rclpy.action", mod)
    cancel = threading.Event()
    cancel.set()
    status, _ = action_backend.run_action_goal("/a", "x/action/A", object(), cancel=cancel)
    assert status == 5 and cancels == [1]
