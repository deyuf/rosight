"""Parameters panel: per-node list, get/set."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input, Static

from rosight.utils.datatable import (
    current_row_key,
    fit_last_column,
    fit_last_column_when_ready,
    sync_table,
)
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
    from rosight.ros.backend import ParameterValue, RosBackend

log = logging.getLogger(__name__)


class ParamsPanel(Vertical):
    BINDINGS = [
        Binding("enter", "load", "Load params"),
        Binding("g", "get", "Reload"),
        Binding("s", "set", "Set value"),
        Binding("y", "yank", "Copy YAML"),
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
        self._params: dict[str, ParameterValue] = {}
        self._params_node: str | None = None

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

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # DataTable consumes `enter` itself, so the panel-level binding never
        # fires; translate the table's RowSelected into the intended action.
        if event.row_key is None or str(event.row_key.value) == PLACEHOLDER_KEY:
            return
        if event.data_table.id == "nodes-table":
            self.selected_node = str(event.row_key.value)
            self.action_load()
        elif event.data_table.id == "params-table":
            self.action_set()

    def open_node(self, fqn: str) -> bool:
        """Select ``fqn`` in the node list and load its parameters."""
        self.selected_node = fqn
        nt = self.query_one("#nodes-table", DataTable)
        keys = [str(r.key.value) for r in nt.ordered_rows]
        if fqn in keys:
            nt.move_cursor(row=keys.index(fqn), animate=False)
        self.action_load()
        return True

    def action_load(self) -> None:
        node = self.selected_node
        ros = self.ros
        if not node or ros is None or not ros.started:
            return
        self.app_.push_status(f"loading params for {node}…")
        self.run_worker(self._load(node), group="params-load", exclusive=True)

    async def _load(self, node: str) -> None:
        ros = self.ros
        if ros is None:
            return

        def fetch() -> list:
            names = ros.list_parameters(node)
            return ros.get_parameters(node, names) if names else []

        try:
            # Two service round-trips (up to seconds each): keep them off the
            # UI loop.
            params = await asyncio.to_thread(fetch)
        except Exception as e:
            self.app_.push_status(f"param load failed: {e}")
            return
        self._params = {p.name: p for p in params}
        self._params_node = node
        self.query_one("#param-header", Static).update(
            Text(f"{node} ({len(params)} parameters) · s: set · y: copy YAML", style="bold cyan")
        )
        pt = self.query_one("#params-table", DataTable)
        rows = [(p.name, (p.name, p.type_name, format_value(p.value))) for p in params]
        if sync_table(pt, rows):
            fit_last_column(pt)
        self.app_.push_status(f"{len(params)} parameters loaded from {node}")

    def _selected_param(self):
        pt = self.query_one("#params-table", DataTable)
        key = current_row_key(pt)
        return self._params.get(key) if key else None

    def action_set(self) -> None:
        import yaml

        from rosight.ros.backend import _build_param_value
        from rosight.ros.yaml_msg import MessageYamlError, parse_yaml
        from rosight.widgets.yaml_form import YamlFormScreen

        param = self._selected_param()
        node = self._params_node
        if param is None or node is None:
            self.app_.notify("load a node's parameters and pick one first", severity="warning")
            return
        text = yaml.safe_dump(param.value, default_flow_style=True).removesuffix("...\n").strip()

        def check(t: str) -> str | None:
            try:
                _build_param_value(SimpleNamespace(), parse_yaml(t), param.type_name)
            except (MessageYamlError, TypeError) as e:
                return str(e)
            return None

        def done(t: str | None) -> None:
            if t is not None:
                value = parse_yaml(t)
                self.run_worker(self._set(node, param.name, value, param.type_name))

        self.app_.push_screen(
            YamlFormScreen(
                f"Set {node} {param.name}  [{param.type_name}]",
                text,
                hint="YAML value, e.g. 1.5, true, 'text', [1, 2]",
                submit_label="Set",
                validate=check,
            ),
            done,
        )

    async def _set(self, node: str, name: str, value: object, type_name: str) -> None:
        ros = self.ros
        if ros is None:
            return
        try:
            ok = await asyncio.to_thread(ros.set_parameter, node, name, value, type_name)
        except Exception as e:
            self.app_.notify(f"set {name} failed: {e}", severity="error")
            return
        if not ok:
            self.app_.notify(f"{node} rejected {name} = {value!r}", severity="warning")
            return
        self.app_.push_status(f"{name} = {value!r}")
        await self._load(node)

    def action_yank(self) -> None:
        """Copy the loaded parameters as a ROS 2 params file."""
        import yaml

        if not self._params or self._params_node is None:
            self.app_.notify("load a node's parameters first", severity="warning")
            return
        doc = {
            self._params_node: {
                "ros__parameters": {n: p.value for n, p in sorted(self._params.items())}
            }
        }
        self.app.copy_to_clipboard(yaml.safe_dump(doc, sort_keys=False))
        self.app_.notify(f"copied {len(self._params)} parameters as YAML", timeout=2)

    def action_get(self) -> None:
        self.action_load()
