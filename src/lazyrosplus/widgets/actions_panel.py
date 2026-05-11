"""Actions panel: list ROS 2 actions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input, Static

from lazyrosplus.utils.datatable import (
    current_row_key,
    fit_last_column,
    fit_last_column_when_ready,
    restore_cursor,
)
from lazyrosplus.utils.formatting import short_type

if TYPE_CHECKING:
    from lazyrosplus.ros.backend import ActionInfo, RosBackend

log = logging.getLogger(__name__)


class ActionsPanel(Vertical):
    BINDINGS = [
        Binding("enter", "show", "Inspect"),
        Binding("/", "filter", "Filter"),
    ]

    DEFAULT_CSS = """
    ActionsPanel { layout: horizontal; overflow: hidden; }
    ActionsPanel > #left {
        width: 50%; min-width: 40;
        border-right: solid $primary 30%;
        overflow: hidden;
    }
    ActionsPanel > #right { width: 1fr; padding: 0 1; overflow: hidden; }
    """

    filter_text: reactive[str] = reactive("")
    selected: reactive[str | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self._action_cache: list[ActionInfo] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Input(placeholder="filter actions…", id="filter")
            yield DataTable(id="act-table", cursor_type="row", zebra_stripes=True)
        with Vertical(id="right"):
            yield Static("Select an action", id="act-header")
            yield Static("", id="act-detail")

    def on_mount(self) -> None:
        table = self.query_one("#act-table", DataTable)
        table.add_columns("Action", "Type")
        fit_last_column_when_ready(table)
        self._refresh()
        self.set_interval(2.0, self._refresh)

    def on_resize(self) -> None:
        fit_last_column_when_ready(self.query_one("#act-table", DataTable))

    @property
    def ros(self) -> RosBackend | None:
        return getattr(self.app, "ros", None)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value
            self._render_table()

    def action_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def _refresh(self) -> None:
        if self.region.width == 0:
            return
        ros = self.ros
        if ros is None or not ros.started:
            return
        try:
            self._action_cache = ros.list_actions()
        except Exception:
            log.exception("list_actions failed")
        self._render_table()

    def on_show(self) -> None:
        self._refresh()

    def _render_table(self) -> None:
        table = self.query_one("#act-table", DataTable)
        scroll = table.scroll_offset
        selected_key = current_row_key(table)
        table.clear()
        ft = self.filter_text.lower().strip()
        new_idx = -1
        idx = 0
        for a in self._action_cache:
            if ft and ft not in a.name.lower() and ft not in a.primary_type.lower():
                continue
            table.add_row(a.name, short_type(a.primary_type), key=a.name)
            if a.name == selected_key:
                new_idx = idx
            idx += 1
        restore_cursor(table, selected_key, new_idx)
        try:
            table.scroll_to(x=scroll.x, y=scroll.y, animate=False)
        except Exception:
            pass
        fit_last_column(table)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        new = str(event.row_key.value)
        if new == self.selected:
            return
        self.selected = new
        self.action_show()

    def action_show(self) -> None:
        a = next((x for x in self._action_cache if x.name == self.selected), None)
        if a is None:
            return
        text = Text()
        text.append(f"{a.name}\n", style="bold cyan")
        text.append(f"types: {', '.join(a.types)}\n", style="dim")
        text.append("\nGoal/feedback monitor coming soon.", style="italic")
        self.query_one("#act-detail", Static).update(text)
