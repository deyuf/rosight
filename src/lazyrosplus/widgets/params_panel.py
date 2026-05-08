"""Parameters panel: per-node list, get/set."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input, Static

from lazyrosplus.utils.formatting import format_value

if TYPE_CHECKING:
    from lazyrosplus.app import LazyrosPlusApp
    from lazyrosplus.ros.backend import RosBackend

log = logging.getLogger(__name__)


class ParamsPanel(Vertical):
    BINDINGS = [
        Binding("enter", "load", "Load params"),
        Binding("g", "get", "Get"),
        Binding("/", "filter", "Filter"),
    ]

    DEFAULT_CSS = """
    ParamsPanel { layout: horizontal; }
    ParamsPanel > #left { width: 35%; min-width: 30; border-right: solid $primary 30%; }
    ParamsPanel > #right { width: 1fr; padding: 0 1; }
    """

    filter_text: reactive[str] = reactive("")
    selected_node: reactive[str | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Input(placeholder="filter nodes…", id="filter")
            yield DataTable(id="nodes-table", cursor_type="row", zebra_stripes=True)
        with Vertical(id="right"):
            yield Static("Select a node and press [enter]", id="param-header")
            yield DataTable(id="params-table", cursor_type="row")

    def on_mount(self) -> None:
        nt = self.query_one("#nodes-table", DataTable)
        nt.add_columns("Node")
        pt = self.query_one("#params-table", DataTable)
        pt.add_columns("Name", "Type", "Value")
        self._refresh_nodes()
        self.set_interval(3.0, self._refresh_nodes)

    @property
    def ros(self) -> RosBackend | None:
        return getattr(self.app, "ros", None)

    @property
    def app_(self) -> LazyrosPlusApp:
        return self.app  # type: ignore[return-value]

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value
            self._refresh_nodes()

    def action_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def _refresh_nodes(self) -> None:
        ros = self.ros
        if ros is None or not ros.started:
            return
        try:
            nodes = ros.list_nodes()
        except Exception:
            log.exception("list_nodes failed")
            return
        nt = self.query_one("#nodes-table", DataTable)
        nt.clear()
        ft = self.filter_text.lower().strip()
        for n in nodes:
            if ft and ft not in n.fqn.lower():
                continue
            nt.add_row(n.fqn, key=n.fqn)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id == "nodes-table" and event.row_key is not None:
            self.selected_node = str(event.row_key.value)

    def action_load(self) -> None:
        node = self.selected_node
        ros = self.ros
        if not node or ros is None:
            return
        self.app_.push_status(f"loading params for {node}…")
        try:
            names = ros.list_parameters(node)
            params = ros.get_parameters(node, names) if names else []
        except Exception as e:
            self.app_.push_status(f"param load failed: {e}")
            return
        self.query_one("#param-header", Static).update(
            Text(f"{node} ({len(params)} parameters)", style="bold cyan")
        )
        pt = self.query_one("#params-table", DataTable)
        pt.clear()
        for p in params:
            pt.add_row(p.name, p.type_name, format_value(p.value), key=p.name)

    def action_get(self) -> None:
        self.action_load()
