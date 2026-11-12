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

from rosight.utils.datatable import fit_last_column, fit_last_column_when_ready, sync_table
from rosight.utils.formatting import format_value
from rosight.utils.fuzzy import matches
from rosight.widgets._base import (
    PLACEHOLDER_KEY,
    empty_state_text,
    fetch_graph_items,
    placeholder_row,
)

if TYPE_CHECKING:
    from rosight.app import RosightApp
    from rosight.ros.backend import RosBackend

log = logging.getLogger(__name__)


class ParamsPanel(Vertical):
    BINDINGS = [
        Binding("enter", "load", "Load params"),
        Binding("g", "get", "Get"),
        Binding("/", "filter", "Filter"),
    ]

    DEFAULT_CSS = """
    ParamsPanel { layout: horizontal; overflow: hidden; }
    ParamsPanel > #left {
        width: 35%; min-width: 30;
        border-right: solid $primary 30%;
        overflow: hidden;
    }
    ParamsPanel > #right { width: 1fr; padding: 0 1; overflow: hidden; }
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
        fit_last_column_when_ready(nt)
        fit_last_column_when_ready(pt)
        self._refresh_nodes()
        self.set_interval(3.0, self._refresh_nodes)

    def on_resize(self) -> None:
        fit_last_column_when_ready(self.query_one("#nodes-table", DataTable))
        fit_last_column_when_ready(self.query_one("#params-table", DataTable))

    def on_show(self) -> None:
        self._refresh_nodes()

    @property
    def ros(self) -> RosBackend | None:
        return getattr(self.app, "ros", None)

    @property
    def app_(self) -> RosightApp:
        return self.app  # type: ignore[return-value]

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value
            self._refresh_nodes()

    def action_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def _refresh_nodes(self) -> None:
        if self.region.width == 0:
            return
        ros = self.ros
        if ros is None or not ros.started:
            return
        try:
            nodes, gen = fetch_graph_items(ros, "nodes", "list_nodes")
        except Exception:
            log.exception("list_nodes failed")
            return
        nt = self.query_one("#nodes-table", DataTable)
        rows = [(n.fqn, (n.fqn,)) for n in nodes if matches(self.filter_text, n.fqn)]
        if not rows:
            rows = [placeholder_row(empty_state_text(ros, gen, self.filter_text, "nodes"), 1)]
        if sync_table(nt, rows):
            fit_last_column(nt)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "nodes-table" or event.row_key is None:
            return
        key = str(event.row_key.value)
        if key != PLACEHOLDER_KEY:
            self.selected_node = key

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
