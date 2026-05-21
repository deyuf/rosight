"""Tests for the command-palette dispatch table.

Two goals:

1. Every documented command resolves to a handler, no orphans.
2. Each handler reacts correctly to missing/invalid args (return False
   → ``unknown command: ...`` toast) and to the happy path.

We use a fresh ``RosightApp`` in headless mode so the panels exist and
``query_one(TopicsPanel)`` succeeds.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.widgets import TabbedContent

from rosight.app import RosightApp
from rosight.ros.backend import RosBackend


def _app() -> RosightApp:
    return RosightApp(ros=RosBackend())


def _statuses(app: RosightApp) -> list[str]:
    """Capture every ``push_status`` call."""
    seen: list[str] = []
    real = app.push_status

    def fake(msg: str) -> None:
        seen.append(msg)
        real(msg)

    app.push_status = fake  # type: ignore[method-assign]
    return seen


@pytest.mark.asyncio
async def test_dispatch_table_covers_every_documented_command():
    """Sanity: the dispatch dict has all the commands we promise."""
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        cmds = pilot.app._commands
        for name in (
            "q",
            "quit",
            "exit",
            "topic",
            "node",
            "param",
            "plot",
            "plot-array",
            "view",
            "record",
            "help",
            "domain",
        ):
            assert name in cmds, f"missing handler for {name!r}"


@pytest.mark.asyncio
async def test_unknown_command_pushes_status():
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        statuses = _statuses(pilot.app)
        pilot.app._on_command_submitted("notacommand foo")
        assert any("unknown command" in s for s in statuses)


@pytest.mark.asyncio
async def test_empty_command_is_noop():
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        statuses = _statuses(pilot.app)
        pilot.app._on_command_submitted("")
        pilot.app._on_command_submitted(None)
        assert statuses == []


@pytest.mark.asyncio
async def test_topic_without_args_is_rejected():
    """``topic`` requires a filter arg — bare ``topic`` should warn."""
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        statuses = _statuses(pilot.app)
        pilot.app._on_command_submitted("topic")
        assert any("unknown" in s for s in statuses)


@pytest.mark.asyncio
async def test_topic_with_arg_switches_tab_and_sets_filter():
    from rosight.widgets.topics_panel import TopicsPanel

    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app._on_command_submitted("topic /chatter")
        await pilot.pause()
        assert pilot.app.query_one(TabbedContent).active == "topics"
        assert pilot.app.query_one(TopicsPanel).filter_text == "/chatter"


@pytest.mark.asyncio
async def test_plot_requires_two_args():
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        statuses = _statuses(pilot.app)
        pilot.app._on_command_submitted("plot /topic")  # missing field path
        assert any("unknown" in s for s in statuses)


@pytest.mark.asyncio
async def test_plot_with_two_args_adds_series():
    from rosight.widgets.plot_panel import PlotPanel

    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app._on_command_submitted("plot /odom twist.linear.x")
        await pilot.pause()
        panel = pilot.app.query_one(PlotPanel)
        assert "/odom/twist.linear.x" in panel._sources


@pytest.mark.asyncio
async def test_plot_array_with_two_args_adds_snapshot_series():
    from rosight.widgets.plot_panel import PlotPanel

    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app._on_command_submitted("plot-array /scan ranges")
        await pilot.pause()
        panel = pilot.app.query_one(PlotPanel)
        _, _, kind, _ = panel._sources["/scan/ranges"]
        assert kind == "array"


@pytest.mark.asyncio
async def test_domain_without_args_is_rejected():
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        statuses = _statuses(pilot.app)
        pilot.app._on_command_submitted("domain")
        assert any("unknown" in s for s in statuses)


@pytest.mark.asyncio
async def test_record_switches_to_bags_tab():
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app._on_command_submitted("record")
        await pilot.pause()
        assert pilot.app.query_one(TabbedContent).active == "bags"


@pytest.mark.asyncio
async def test_quit_aliases_all_exit():
    """``q``, ``quit``, ``exit`` all map to the same handler."""
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        cmds = pilot.app._commands
        # Identity: all three resolve to the same bound method.
        assert cmds["q"] == cmds["quit"] == cmds["exit"]
