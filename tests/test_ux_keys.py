"""Quit confirmation and vim-style motions."""

from __future__ import annotations

from dataclasses import replace

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Input, TabbedContent, Tree

from rosight.app import RosightApp
from rosight.ros.backend import RosBackend, ServiceInfo
from rosight.ros.discovery import GraphSnapshot
from rosight.widgets.bags_panel import BagsPanel
from rosight.widgets.confirm_screen import ConfirmScreen
from rosight.widgets.services_panel import ServicesPanel


class _Running:
    pid = 1
    returncode = None

    def poll(self):
        return self.returncode

    def send_signal(self, _sig):
        self.returncode = -2

    def wait(self, timeout=None):
        return self.returncode


def _app(vim: bool = True) -> RosightApp:
    app = RosightApp(ros=RosBackend())
    app.config = replace(app.config, ui=replace(app.config.ui, vim_keys=vim))
    return app


@pytest.mark.asyncio
async def test_quit_without_bag_exits_immediately():
    app = _app()
    async with app.run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.press("q")
        await pilot.pause()
    assert app.return_code == 0


@pytest.mark.asyncio
async def test_quit_while_recording_asks_first():
    app = _app()
    async with app.run_test(headless=True, size=(120, 30)) as pilot:
        bags = pilot.app.query_one(BagsPanel)
        bags._record_proc = _Running()
        await pilot.press("q")
        await pilot.pause()
        assert isinstance(pilot.app.screen, ConfirmScreen)
        assert "record" in str(pilot.app.screen.question)
        await pilot.press("n")
        await pilot.pause()
        assert not isinstance(pilot.app.screen, ConfirmScreen)
        assert pilot.app.is_running
        await pilot.press("q")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
    assert app.return_code == 0


def _services_snapshot() -> GraphSnapshot:
    return GraphSnapshot(
        services=tuple(ServiceInfo(f"/s{i}", ("std_srvs/srv/Empty",)) for i in range(5)),
        generation=1,
    )


class _Ros:
    started = True
    executor_alive = True
    domain_id = 0

    def graph_snapshot(self):
        return _services_snapshot()

    def active_subscriptions(self):
        return []

    def stop(self):
        pass


async def _services_table(pilot) -> DataTable:
    pilot.app.ros = _Ros()  # type: ignore[assignment]
    pilot.app.query_one(TabbedContent).active = "services"
    for _ in range(3):
        await pilot.pause()
    pilot.app.query_one(ServicesPanel)._refresh(force=True)
    table = pilot.app.query_one("#srv-table", DataTable)
    table.focus()
    await pilot.pause()
    return table


@pytest.mark.asyncio
async def test_vim_motions_move_table_cursor():
    async with _app(vim=True).run_test(headless=True, size=(140, 40)) as pilot:
        table = await _services_table(pilot)
        await pilot.press("j", "j")
        assert table.cursor_row == 2
        await pilot.press("k")
        assert table.cursor_row == 1
        await pilot.press("G")
        assert table.cursor_row == 4
        await pilot.press("g")
        assert table.cursor_row == 0


@pytest.mark.asyncio
async def test_vim_motions_disabled_by_config():
    async with _app(vim=False).run_test(headless=True, size=(140, 40)) as pilot:
        table = await _services_table(pilot)
        await pilot.press("j", "j")
        assert table.cursor_row == 0


@pytest.mark.asyncio
async def test_vim_keys_type_into_filter_input():
    async with _app(vim=True).run_test(headless=True, size=(140, 40)) as pilot:
        await _services_table(pilot)
        flt = pilot.app.query_one(ServicesPanel).query_one("#filter", Input)
        flt.focus()
        await pilot.pause()
        await pilot.press("j", "k", "g")
        assert flt.value == "jkg"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("start", "table", "key", "target"),
    [
        ("services", "#srv-table", "6", "plot"),
        ("actions", "#act-table", "2", "nodes"),
        ("topics", "#topics-table", "8", "bags"),
    ],
)
async def test_number_keys_switch_tabs_while_a_table_has_focus(start, table, key, target):
    """Regression: the focused table's pane was re-activated, so 1-9 did
    nothing once you had used a table."""
    async with _app().run_test(headless=True, size=(140, 40)) as pilot:
        pilot.app.query_one(TabbedContent).active = start
        for _ in range(3):
            await pilot.pause()
        pilot.app.query_one(table).focus()
        await pilot.pause()
        await pilot.press(key)
        for _ in range(3):
            await pilot.pause()
        assert pilot.app.query_one(TabbedContent).active == target
        focused = pilot.app.focused
        assert focused is not None and isinstance(focused, DataTable | Tree)
        assert target in [a.id for a in focused.ancestors if a.id]
