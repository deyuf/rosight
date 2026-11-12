"""Nodes panel: list nodes and show their endpoints."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static

from rosight.utils.formatting import short_type
from rosight.widgets._base import GraphListPanel


class NodesPanel(GraphListPanel):
    BINDINGS = [
        Binding("enter", "info", "Info"),
        Binding("/", "filter", "Filter"),
    ]

    DEFAULT_CSS = """
    NodesPanel { layout: horizontal; overflow: hidden; }
    NodesPanel > #left {
        width: 40%; min-width: 30;
        border-right: solid $primary 30%;
        overflow: hidden;
    }
    NodesPanel > #right { width: 1fr; padding: 0 1; overflow: hidden; }
    NodesPanel #node-detail { height: 1fr; }
    """

    TABLE_ID = "nodes-table"
    COLUMNS = ("Node", "Namespace")
    GRAPH_FIELD = "nodes"
    LIST_METHOD = "list_nodes"
    CACHE_ATTR = "_node_cache"
    NOUN = "nodes"
    REFRESH_SECONDS = 2.0

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Input(placeholder="filter nodes… (fuzzy)", id="filter")
            yield DataTable(id=self.TABLE_ID, cursor_type="row", zebra_stripes=True)
        with Vertical(id="right"):
            yield Static("Select a node", id="node-header")
            yield Static("", id="node-detail")

    def _row_key(self, item: Any) -> str:
        return str(item.fqn)

    def _row_cells(self, item: Any) -> tuple[Any, ...]:
        return (item.name, item.namespace)

    def _match_fields(self, item: Any) -> tuple[str, ...]:
        return (item.fqn,)

    def _on_selected(self) -> None:
        self.action_info()

    def action_info(self) -> None:
        node = self.selected
        ros = self.ros
        if not node or ros is None:
            return
        try:
            info = ros.node_info(node)
        except Exception as e:
            self.query_one("#node-detail", Static).update(Text(f"error: {e}", style="red"))
            return
        self.query_one("#node-header", Static).update(Text(node, style="bold cyan"))
        text = Text()
        for label, items in info.items():
            text.append(f"\n{label} ({len(items)})\n", style="bold yellow")
            for name, types in items:
                text.append(f"  {name}", style="white")
                if types:
                    text.append(f"  [{short_type(types[0])}]\n", style="dim")
                else:
                    text.append("\n")
        self.query_one("#node-detail", Static).update(text)
