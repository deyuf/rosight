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
    ActionsPanel { layout: horizontal; }
    ActionsPanel > #left { width: 50%; min-width: 40; border-right: solid $primary 30%; }
    ActionsPanel > #right { width: 1fr; padding: 0 1; }
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
        self._refresh()
        self.set_interval(2.0, self._refresh)

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
        ros = self.ros
        if ros is None or not ros.started:
            return
        try:
            self._action_cache = ros.list_actions()
        except Exception:
            log.exception("list_actions failed")
        self._render_table()

    def _render_table(self) -> None:
        table = self.query_one("#act-table", DataTable)
        table.clear()
        ft = self.filter_text.lower().strip()
        for a in self._action_cache:
            if ft and ft not in a.name.lower() and ft not in a.primary_type.lower():
                continue
            table.add_row(a.name, short_type(a.primary_type), key=a.name)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:
            self.selected = str(event.row_key.value)
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
