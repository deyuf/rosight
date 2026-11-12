"""Message tree flash/search/copy and paused echo history."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from textual.app import App, ComposeResult
from textual.widgets import Input, TabbedContent

import rosight.ros.backend as backend_mod
from rosight.app import RosightApp
from rosight.ros.backend import RosBackend, Subscription, TopicInfo
from rosight.ros.discovery import GraphSnapshot
from rosight.widgets.message_tree import MessageTree
from rosight.widgets.topics_panel import TopicsPanel

# ----- Subscription history ring ---------------------------------------------


def test_history_ring_bounded_by_count(monkeypatch):
    monkeypatch.setattr(backend_mod, "HISTORY_LEN", 5)
    sub = Subscription("/x", "t", decode=lambda b: b.decode())
    for i in range(12):
        sub.ingest_raw(f"m{i}".encode())
    hist = sub.history()
    assert len(hist) == 5
    assert [sub.decode_entry(e) for e in hist] == ["m7", "m8", "m9", "m10", "m11"]


def test_history_ring_bounded_by_bytes(monkeypatch):
    monkeypatch.setattr(backend_mod, "HISTORY_BYTES", 2500)
    sub = Subscription("/img", "t", decode=len)
    for _ in range(10):
        sub.ingest_raw(b"x" * 1000)
    assert len(sub.history()) == 2, "1 MB frames must not pile up past the byte cap"


def test_history_keeps_at_least_one_oversized_message(monkeypatch):
    monkeypatch.setattr(backend_mod, "HISTORY_BYTES", 10)
    sub = Subscription("/img", "t", decode=len)
    sub.ingest_raw(b"x" * 1000)
    assert len(sub.history()) == 1


def test_history_decoded_mode_returns_objects(monkeypatch):
    monkeypatch.setattr(backend_mod, "estimate_msg_size", lambda _m: 8)
    sub = Subscription("/x", "t")
    sub.ingest_msg(SimpleNamespace(v=1))
    (entry,) = sub.history()
    assert sub.decode_entry(entry).v == 1


# ----- MessageTree: flash, search, copy -----------------------------------------


class _Vec:
    def __init__(self, x, y):
        self.x, self.y = x, y

    @staticmethod
    def get_fields_and_field_types():
        return {"x": "float64", "y": "float64"}


class _Pose:
    def __init__(self, x=0.0):
        self.position = _Vec(x, 0.0)
        self.orientation = _Vec(0.0, 1.0)

    @staticmethod
    def get_fields_and_field_types():
        return {"position": "geometry_msgs/Point", "orientation": "geometry_msgs/Point"}


class _TreeApp(App):
    def compose(self) -> ComposeResult:
        yield MessageTree(id="tree")


def _value_style(node) -> str:
    label = node.label
    return " ".join(str(span.style) for span in label.spans)


@pytest.mark.asyncio
async def test_changed_value_flashes_then_clears():
    async with _TreeApp().run_test(size=(80, 30)) as pilot:
        tree = pilot.app.query_one(MessageTree)
        tree.update_message(_Pose(1.0))
        tree.update_message(_Pose(2.0))
        node_x = tree._nodes_by_path["position.x"]
        assert "on yellow" in _value_style(node_x)
        assert "on yellow" not in _value_style(tree._nodes_by_path["position.y"])
        tree._flash = dict.fromkeys(tree._flash, 0.0)  # expire now
        tree._expire_flash()
        assert "on yellow" not in _value_style(node_x)


@pytest.mark.asyncio
async def test_search_moves_cursor_expands_and_wraps():
    async with _TreeApp().run_test(size=(80, 30)) as pilot:
        tree = pilot.app.query_one(MessageTree)
        tree.update_message(_Pose())
        await pilot.pause()
        tree._nodes_by_path["orientation"].collapse()
        await pilot.pause()
        assert tree.search("orientation.y", from_start=True)
        await pilot.pause()
        assert tree.cursor_node is tree._nodes_by_path["orientation.y"]
        assert tree._nodes_by_path["orientation"].is_expanded

        # "x" matches position.x then orientation.x, then wraps.
        assert tree.search("x", from_start=True)
        await pilot.pause()
        assert tree.cursor_node.data.path == "position.x"
        tree.action_search_next()
        await pilot.pause()
        assert tree.cursor_node.data.path == "orientation.x"
        tree.action_search_next()
        await pilot.pause()
        assert tree.cursor_node.data.path == "position.x"
        tree.action_search_prev()
        await pilot.pause()
        assert tree.cursor_node.data.path == "orientation.x"
        assert not tree.search("nonexistent")


@pytest.mark.asyncio
async def test_yank_copies_path_and_value():
    async with _TreeApp().run_test(size=(80, 30)) as pilot:
        copied: list[str] = []
        pilot.app.copy_to_clipboard = copied.append  # type: ignore[method-assign]
        tree = pilot.app.query_one(MessageTree)
        tree.update_message(_Pose(3.25))
        await pilot.pause()
        tree.move_cursor(tree._nodes_by_path["position.x"])
        await pilot.pause()
        await pilot.press("y")
        await pilot.press("Y")
        assert copied == ["position.x", "3.25"]


# ----- Topics panel: search box + paused history ---------------------------------


class _Ros:
    def __init__(self, sub: Subscription):
        self.started = True
        self.executor_alive = True
        self.domain_id = 0
        self.sub = sub

    def graph_snapshot(self):
        return GraphSnapshot(topics=(TopicInfo("/pose", ("g/Pose",), 1, 0),), generation=1)

    def active_subscriptions(self):
        return [self.sub]

    def get_subscription(self, topic):
        return self.sub if topic == "/pose" else None

    def stop(self):
        pass


async def _topics(pilot, sub):
    pilot.app.ros = _Ros(sub)  # type: ignore[assignment]
    pilot.app.query_one(TabbedContent).active = "topics"
    for _ in range(2):
        await pilot.pause()
    panel = pilot.app.query_one(TopicsPanel)
    panel.selected_topic = "/pose"
    return panel


@pytest.mark.asyncio
async def test_paused_history_steps_through_messages(monkeypatch):
    monkeypatch.setattr(backend_mod, "estimate_msg_size", lambda _m: 8)
    sub = Subscription("/pose", "g/Pose")
    for i in range(3):
        sub.ingest_msg(_Pose(float(i)))
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 40)) as pilot:
        panel = await _topics(pilot, sub)
        tree = pilot.app.query_one("#msg-tree", MessageTree)
        panel._refresh_detail()
        assert tree._nodes_by_path["position.x"].data.value == 2.0

        panel.action_history(1)  # not paused → just a hint
        assert "pause first" in pilot.app.query_one("#status").message

        panel.action_toggle_pause()
        sub.ingest_msg(_Pose(99.0))  # arrives while paused; frozen view ignores it
        panel.action_history(1)
        assert tree._nodes_by_path["position.x"].data.value == 1.0
        panel.action_history(1)
        panel.action_history(1)  # clamps at oldest
        assert tree._nodes_by_path["position.x"].data.value == 0.0
        assert "message 1/3" in str(pilot.app.query_one("#detail-header").render())
        panel.action_history(-1)
        assert tree._nodes_by_path["position.x"].data.value == 1.0

        panel.action_toggle_pause()  # back to live
        assert tree._nodes_by_path["position.x"].data.value == 99.0


@pytest.mark.asyncio
async def test_tree_search_box_flow(monkeypatch):
    monkeypatch.setattr(backend_mod, "estimate_msg_size", lambda _m: 8)
    sub = Subscription("/pose", "g/Pose")
    sub.ingest_msg(_Pose(1.0))
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 40)) as pilot:
        panel = await _topics(pilot, sub)
        panel._refresh_detail()
        tree = pilot.app.query_one("#msg-tree", MessageTree)
        tree.focus()
        await pilot.pause()
        await pilot.press("slash")
        await pilot.pause()
        box = pilot.app.query_one("#tree-search", Input)
        assert box.has_class("-visible") and box.has_focus
        await pilot.press(*"orientation.y")
        await pilot.press("enter")
        await pilot.pause()
        await pilot.pause()
        assert not box.has_class("-visible")
        assert tree.has_focus
        assert tree.cursor_node.data.path == "orientation.y"
