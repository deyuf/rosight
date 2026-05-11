"""Nodes panel: list nodes and show their endpoints."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input, Static

from lazyrosplus.utils.datatable import current_row_key, restore_cursor
from lazyrosplus.utils.formatting import short_type

if TYPE_CHECKING:
    from lazyrosplus.app import LazyrosPlusApp
    from lazyrosplus.ros.backend import NodeInfo, RosBackend

log = logging.getLogger(__name__)


class NodesPanel(Vertical):
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

    filter_text: reactive[str] = reactive("")
    selected: reactive[str | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self._node_cache: list[NodeInfo] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Input(placeholder="filter nodes…", id="filter")
            yield DataTable(id="nodes-table", cursor_type="row", zebra_stripes=True)
        with Vertical(id="right"):
            yield Static("Select a node", id="node-header")
            yield Static("", id="node-detail")

    def on_mount(self) -> None:
        table = self.query_one("#nodes-table", DataTable)
        table.add_columns("Node", "Namespace")
        self._refresh()
        self.set_interval(2.0, self._refresh)

    @property
    def app_(self) -> LazyrosPlusApp:
        return self.app  # type: ignore[return-value]

    @property
    def ros(self) -> RosBackend | None:
        return getattr(self.app_, "ros", None)

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
            self._node_cache = ros.list_nodes()
        except Exception:
            log.exception("list_nodes failed")
            return
        self._render_table()

    def _render_table(self) -> None:
        table = self.query_one("#nodes-table", DataTable)
        selected_key = current_row_key(table)
        table.clear()
        ft = self.filter_text.lower().strip()
        new_idx = -1
        idx = 0
        for n in self._node_cache:
            if ft and ft not in n.fqn.lower():
                continue
            table.add_row(n.name, n.namespace, key=n.fqn)
            if n.fqn == selected_key:
                new_idx = idx
            idx += 1
        restore_cursor(table, selected_key, new_idx)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        self.selected = str(event.row_key.value)
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
