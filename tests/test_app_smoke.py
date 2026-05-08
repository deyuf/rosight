"""Headless smoke tests for the Textual app.

These tests start the app with a no-op RosBackend (so ROS calls can't run)
and verify key bindings work end-to-end.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from lazyros.app import LazyrosApp
from lazyros.ros.backend import RosBackend


def _app() -> LazyrosApp:
    ros = RosBackend()  # not started — backend_ok stays False
    return LazyrosApp(ros=ros)


@pytest.mark.asyncio
async def test_app_starts_without_ros():
    async with _app().run_test(headless=True, size=(120, 40)) as pilot:
        await pilot.pause()
        # The status bar should reflect the no-ros state
        bar = pilot.app.query_one("#status")
        assert bar.backend_ok is False


@pytest.mark.asyncio
async def test_help_modal_opens_and_closes():
    async with _app().run_test(headless=True, size=(120, 40)) as pilot:
        await pilot.press("?")
        await pilot.pause()
        # Help screen should be on top of the screen stack
        assert any("HelpScreen" in type(s).__name__ for s in pilot.app.screen_stack)
        await pilot.press("escape")
        await pilot.pause()
        assert all("HelpScreen" not in type(s).__name__ for s in pilot.app.screen_stack)


@pytest.mark.asyncio
async def test_tab_switching_with_number_keys():
    async with _app().run_test(headless=True, size=(120, 40)) as pilot:
        from textual.widgets import TabbedContent

        await pilot.pause()
        for digit, expected in [
            ("2", "nodes"),
            ("3", "services"),
            ("6", "plot"),
            ("1", "topics"),
        ]:
            await pilot.press(digit)
            await pilot.pause()
            tabs = pilot.app.query_one(TabbedContent)
            assert tabs.active == expected, f"key {digit} -> {tabs.active}"


@pytest.mark.asyncio
async def test_quit_action_exits_cleanly():
    app = _app()
    async with app.run_test(headless=True, size=(120, 40)) as pilot:
        await pilot.pause()
        await pilot.press("q")
        await pilot.pause()
    # exit code from action_quit is None or 0
    assert app.return_code in (0, None)
