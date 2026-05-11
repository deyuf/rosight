"""Services panel: discover and call services."""

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
    from lazyrosplus.ros.backend import RosBackend, ServiceInfo

log = logging.getLogger(__name__)


class ServicesPanel(Vertical):
    BINDINGS = [
        Binding("enter", "show", "Inspect"),
        Binding("c", "call", "Call"),
        Binding("/", "filter", "Filter"),
    ]

    DEFAULT_CSS = """
    ServicesPanel { layout: horizontal; overflow: hidden; }
    ServicesPanel > #left {
        width: 50%; min-width: 40;
        border-right: solid $primary 30%;
        overflow: hidden;
    }
    ServicesPanel > #right { width: 1fr; padding: 0 1; overflow: hidden; }
    """

    filter_text: reactive[str] = reactive("")
    selected: reactive[str | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self._svc_cache: list[ServiceInfo] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Input(placeholder="filter services…", id="filter")
            yield DataTable(id="srv-table", cursor_type="row", zebra_stripes=True)
        with Vertical(id="right"):
            yield Static("Select a service", id="srv-header")
            yield Static("", id="srv-detail")

    def on_mount(self) -> None:
        table = self.query_one("#srv-table", DataTable)
        table.add_columns("Service", "Type")
        self._refresh()
        self.set_interval(2.0, self._refresh)

    @property
    def ros(self) -> RosBackend | None:
        return getattr(self.app, "ros", None)

    @property
    def app_(self) -> LazyrosPlusApp:
        return self.app  # type: ignore[return-value]

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
            self._svc_cache = ros.list_services()
        except Exception:
            log.exception("list_services failed")
        self._render_table()

    def _render_table(self) -> None:
        table = self.query_one("#srv-table", DataTable)
        selected_key = current_row_key(table)
        table.clear()
        ft = self.filter_text.lower().strip()
        new_idx = -1
        idx = 0
        for s in self._svc_cache:
            if ft and ft not in s.name.lower() and ft not in s.primary_type.lower():
                continue
            table.add_row(s.name, short_type(s.primary_type), key=s.name)
            if s.name == selected_key:
                new_idx = idx
            idx += 1
        restore_cursor(table, selected_key, new_idx)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is not None:
            self.selected = str(event.row_key.value)
            self.action_show()

    def action_show(self) -> None:
        s = next((x for x in self._svc_cache if x.name == self.selected), None)
        if s is None:
            return
        text = Text()
        text.append(f"{s.name}\n", style="bold cyan")
        text.append(f"types: {', '.join(s.types)}\n", style="dim")
        text.append("\nPress [c] to call. Auto-form coming soon.", style="italic")
        self.query_one("#srv-detail", Static).update(text)

    def action_call(self) -> None:  # pragma: no cover — interactive
        self.app_.push_status("service-call form not yet implemented in this build")
