"""UI state persistence, plot resubscription, command palette completion/history."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

pytest.importorskip("textual")

from textual.widgets import Input, TabbedContent

from rosight.app import RosightApp
from rosight.config import dump_state_toml, load_user_state, save_user_state
from rosight.ros.backend import RosBackend, TopicInfo
from rosight.ros.discovery import GraphSnapshot
from rosight.widgets.command_palette import CommandPalette, CommandSuggester
from rosight.widgets.plot_panel import PlotPanel
from rosight.widgets.services_panel import ServicesPanel

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


# ----- state file ----------------------------------------------------------------


def test_state_toml_roundtrip_nested_lists_unicode():
    state = {
        "theme": 'quo"te\\d',
        "last_tab": "plot",
        "plot_series": ["scalar|/odom|pose.x", "array|/scan|ranges"],
        "command_history": ["plot /odom pose.x", "domain 3", "名字"],
        "filters": {"topics": "odm", "services": ""},
        "skip_me": object(),
    }
    parsed = tomllib.loads(dump_state_toml(state))
    expected = {k: v for k, v in state.items() if k != "skip_me"}
    assert parsed == expected


def test_save_user_state_keeps_other_keys():
    save_user_state({"theme": "x", "filters": {"topics": "a"}})
    assert load_user_state() == {"theme": "x", "filters": {"topics": "a"}}


# ----- persistence across app runs ---------------------------------------------


class _Ros:
    def __init__(self):
        self.started = True
        self.executor_alive = True
        self.domain_id = 0
        self.subs: dict = {}
        self.fail_subscribe = 0
        self.subscribe_calls = 0

    def graph_snapshot(self):
        return GraphSnapshot(topics=(TopicInfo("/odom", ("nav_msgs/msg/Odometry",)),), generation=1)

    def active_subscriptions(self):
        return list(self.subs.values())

    def get_subscription(self, topic):
        return self.subs.get(topic)

    def subscribe(self, topic, type_name=None, **_kw):
        self.subscribe_calls += 1
        if self.fail_subscribe:
            self.fail_subscribe -= 1
            raise ValueError("topic has no known type")
        sub = SimpleNamespace(topic=topic, snapshot=lambda: (None, 0.0))
        self.subs[topic] = sub
        return sub

    def unsubscribe(self, topic):
        self.subs.pop(topic, None)

    def stop(self):
        pass


@pytest.mark.asyncio
async def test_ui_state_survives_restart():
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(160, 45)) as pilot:
        pilot.app.query_one(ServicesPanel).filter_text = "add"
        pilot.app.query_one(PlotPanel).add_series("/odom", "pose.pose.position.x")
        pilot.app._on_command_submitted("domain abc")
        pilot.app.query_one(TabbedContent).active = "services"
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()

    state = load_user_state()
    assert state["last_tab"] == "services"
    assert state["filters"]["services"] == "add"
    assert state["plot_series"] == ["scalar|/odom|pose.pose.position.x"]
    assert state["command_history"] == ["domain abc"]

    app2 = RosightApp(ros=RosBackend())
    async with app2.run_test(headless=True, size=(160, 45)) as pilot:
        await pilot.pause()
        assert pilot.app.query_one(TabbedContent).active == "services"
        services = pilot.app.query_one(ServicesPanel)
        assert services.filter_text == "add"
        assert services.query_one("#filter", Input).value == "add"
        assert "/odom/pose.pose.position.x" in pilot.app.query_one(PlotPanel)._sources
        assert pilot.app._cmd_history == ["domain abc"]


# ----- plot resubscription --------------------------------------------------------


@pytest.mark.asyncio
async def test_plot_retries_until_topic_is_discovered(monkeypatch):
    monkeypatch.setattr(PlotPanel, "RESUBSCRIBE_PERIOD", 0.0)
    ros = _Ros()
    ros.fail_subscribe = 2  # not discovered yet for two attempts
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        plot = pilot.app.query_one(PlotPanel)
        plot.add_series("/odom", "pose.pose.position.x")  # attempt 1 fails
        assert "/odom" not in ros.subs
        plot._sample()  # attempt 2 fails
        plot._sample()  # attempt 3 succeeds
        assert "/odom" in ros.subs


@pytest.mark.asyncio
async def test_plot_does_not_resubscribe_after_user_unsubscribed(monkeypatch):
    monkeypatch.setattr(PlotPanel, "RESUBSCRIBE_PERIOD", 0.0)
    ros = _Ros()
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        plot = pilot.app.query_one(PlotPanel)
        plot.add_series("/odom", "pose.pose.position.x")
        assert pilot.app.unsubscribe_topic("/odom")
        calls = ros.subscribe_calls
        for _ in range(3):
            plot._sample()
        assert ros.subscribe_calls == calls, "explicit unsubscribe must stick"
        plot.add_series("/odom", "twist.twist.linear.x")  # explicit add → resume
        assert "/odom" in ros.subs


@pytest.mark.asyncio
async def test_plot_resubscribes_after_reconnect_cleared_subscriptions(monkeypatch):
    monkeypatch.setattr(PlotPanel, "RESUBSCRIBE_PERIOD", 0.0)
    ros = _Ros()
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        plot = pilot.app.query_one(PlotPanel)
        plot.add_series("/odom", "pose.pose.position.x")
        ros.subs.clear()  # what :reconnect / :domain do
        plot._sample()
        assert "/odom" in ros.subs


# ----- palette completion + history ---------------------------------------------


def _suggester():
    return CommandSuggester(
        ["plot", "plot-array", "topic", "unsub", "domain", "quit"],
        topics=lambda: ["/odom", "/scan"],
        fields=lambda topic, arrays: (
            (["ranges"] if arrays else ["pose.pose.position.x", "pose.pose.position.y"])
            if topic in ("/odom", "/scan")
            else []
        ),
    )


@pytest.mark.parametrize(
    ("typed", "suggested"),
    [
        ("do", "domain"),
        ("plot", "plot-array"),
        ("plot /o", "plot /odom"),
        ("plot /odom pose.pose.position.", "plot /odom pose.pose.position.x"),
        ("plot-array /scan r", "plot-array /scan ranges"),
        ("unsub a", "unsub all"),
        ("topic /s", "topic /scan"),
        ("domain 3", None),
        ("plot /nope p", None),
        ("zzz", None),
    ],
)
def test_suggester(typed, suggested):
    assert _suggester().suggest(typed) == suggested


@pytest.mark.asyncio
async def test_palette_history_navigation():
    results: list = []
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(140, 40)) as pilot:
        pilot.app.push_screen(CommandPalette(history=["first", "second"]), results.append)
        await pilot.pause()
        box = pilot.app.screen.query_one("#cmd-input", Input)
        await pilot.press("up")
        assert box.value == "second"
        await pilot.press("up", "up")
        assert box.value == "first"
        await pilot.press("down", "down")
        assert box.value == ""
        await pilot.press("up", "enter")
        await pilot.pause()
    assert results == ["second"]


@pytest.mark.asyncio
async def test_palette_accepts_completion_with_right_arrow():
    ros = _Ros()
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(140, 40)) as pilot:
        pilot.app.ros = ros  # type: ignore[assignment]
        pilot.app.action_command()
        await pilot.pause()
        await pilot.press(*"plot /o")
        await pilot.pause()
        await pilot.press("right")
        box = pilot.app.screen.query_one("#cmd-input", Input)
        assert box.value == "plot /odom"
