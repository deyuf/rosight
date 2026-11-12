"""Nodes panel: list nodes and show their endpoints."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static, Tree

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
            tree: Tree[tuple[str, str]] = Tree("endpoints", id="node-detail")
            tree.show_root = False
            yield tree

    def _row_key(self, item: Any) -> str:
        return str(item.fqn)

    def _row_cells(self, item: Any) -> tuple[Any, ...]:
        return (item.name, item.namespace)

    def _match_fields(self, item: Any) -> tuple[str, ...]:
        return (item.fqn,)

    def _on_selected(self) -> None:
        self.action_info()

    # Section label, and where enter on one of its entries takes you.
    _SECTIONS = {
        "publishers": ("Publishers", "topic"),
        "subscribers": ("Subscribers", "topic"),
        "service_servers": ("Service servers", "service"),
        "service_clients": ("Service clients", "service"),
        "action_servers": ("Action servers", "action"),
        "action_clients": ("Action clients", "action"),
    }

    def action_info(self) -> None:
        node = self.selected
        ros = self.ros
        if not node or ros is None:
            return
        header = self.query_one("#node-header", Static)
        tree = self.query_one("#node-detail", Tree)
        tree.clear()
        try:
            info = ros.node_info(node)
        except Exception as e:
            header.update(Text(f"{node}\nerror: {e}", style="red"))
            return
        header.update(
            Text.assemble((f"{node}\n", "bold cyan"), ("enter on an entry: jump to it", "dim"))
        )
        for key, items in info.items():
            title, kind = self._SECTIONS.get(key, (key, ""))
            section = tree.root.add(
                Text.assemble((title, "bold yellow"), (f"  ({len(items)})", "dim")),
                expand=bool(items),
            )
            for name, types in items:
                label = Text(name)
                if types:
                    label.append(f"  [{short_type(types[0])}]", style="dim")
                section.add_leaf(label, data=(kind, name))

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        data = event.node.data
        if not data:
            return
        kind, name = data
        goto = getattr(self.app, f"goto_{kind}", None)
        if callable(goto):
            goto(name)
