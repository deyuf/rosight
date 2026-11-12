"""Actions panel: list ROS 2 actions."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static

from rosight.utils.formatting import short_type
from rosight.widgets._base import GraphListPanel


class ActionsPanel(GraphListPanel):
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

    TABLE_ID = "act-table"
    COLUMNS = ("Action", "Type")
    GRAPH_FIELD = "actions"
    LIST_METHOD = "list_actions"
    CACHE_ATTR = "_action_cache"
    NOUN = "actions"
    REFRESH_SECONDS = 2.0

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Input(placeholder="filter actions… (fuzzy)", id="filter")
            yield DataTable(id=self.TABLE_ID, cursor_type="row", zebra_stripes=True)
        with Vertical(id="right"):
            yield Static("Select an action", id="act-header")
            yield Static("", id="act-detail")

    def _row_cells(self, item: Any) -> tuple[Any, ...]:
        return (item.name, short_type(item.primary_type))

    def _match_fields(self, item: Any) -> tuple[str, ...]:
        return (item.name, item.primary_type)

    def _on_selected(self) -> None:
        self.action_show()

    def action_show(self) -> None:
        a = next((x for x in self.items if x.name == self.selected), None)
        if a is None:
            return
        text = Text()
        text.append(f"{a.name}\n", style="bold cyan")
        text.append(f"types: {', '.join(a.types)}\n", style="dim")
        text.append("\nGoal/feedback monitor coming soon.", style="italic")
        self.query_one("#act-detail", Static).update(text)
