"""Interfaces panel: browse msg/srv/action definitions."""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input, Static

if TYPE_CHECKING:
    pass


class InterfacesPanel(Vertical):
    BINDINGS = [
        Binding("/", "filter", "Filter"),
        Binding("enter", "show", "Show"),
    ]

    DEFAULT_CSS = """
    InterfacesPanel { layout: horizontal; }
    InterfacesPanel > #left { width: 40%; min-width: 30; border-right: solid $primary 30%; }
    InterfacesPanel > #right { width: 1fr; padding: 0 1; }
    InterfacesPanel #iface-detail { height: 1fr; }
    """

    filter_text: reactive[str] = reactive("")

    def __init__(self) -> None:
        super().__init__()
        self._cache: list[tuple[str, str]] = []  # (name, kind)

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Input(placeholder="filter interfaces…", id="filter")
            yield DataTable(id="iface-table", cursor_type="row", zebra_stripes=True)
        with Vertical(id="right"):
            yield Static("Select an interface", id="iface-header")
            yield Static("", id="iface-detail")

    def on_mount(self) -> None:
        t = self.query_one("#iface-table", DataTable)
        t.add_columns("Type", "Kind")
        self._discover()
        self._render()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value
            self._render()

    def action_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    # ---- discovery -----------------------------------------------------

    # Heuristic — only inspect packages that look like ROS interface packages.
    _ROS_PKG_SUFFIXES = ("_msgs", "_interfaces", "_srvs", "_actions")

    def _discover(self) -> None:
        out: list[tuple[str, str]] = []
        try:
            roots: list[str] = []
            for _finder, name, ispkg in pkgutil.iter_modules():
                if not ispkg:
                    continue
                if not name.endswith(self._ROS_PKG_SUFFIXES):
                    continue
                roots.append(name)
            for pkg in roots:
                for kind in ("msg", "srv", "action"):
                    mod_name = f"{pkg}.{kind}"
                    try:
                        m = importlib.import_module(mod_name)
                    except BaseException:
                        # ROS interface packages can fail to import for many
                        # reasons (missing native libs, mis-installed deps).
                        # Tolerate everything — including PyO3 PanicExceptions.
                        continue
                    members = getattr(m, "__all__", None) or [
                        a for a in dir(m) if not a.startswith("_")
                    ]
                    for attr in members:
                        cls = getattr(m, attr, None)
                        if cls is None or not isinstance(cls, type):
                            continue
                        out.append((f"{pkg}/{kind}/{attr}", kind))
        except BaseException:
            pass
        out.sort()
        self._cache = out

    def _render(self) -> None:
        t = self.query_one("#iface-table", DataTable)
        t.clear()
        ft = self.filter_text.lower().strip()
        for name, kind in self._cache:
            if ft and ft not in name.lower():
                continue
            t.add_row(name, kind, key=name)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        name = str(event.row_key.value)
        self._show(name)

    def action_show(self) -> None:
        t = self.query_one("#iface-table", DataTable)
        if t.cursor_row is None:
            return
        try:
            row_key, _ = t.coordinate_to_cell_key((t.cursor_row, 0))
            if row_key:
                self._show(str(row_key.value))
        except Exception:
            return

    def _show(self, name: str) -> None:
        try:
            from lazyros.ros.introspection import (
                get_action_class,
                get_message_class,
                get_service_class,
            )

            parts = name.split("/")
            if len(parts) == 3:
                kind = parts[1]
            else:
                kind = "msg"
            if kind == "msg":
                cls = get_message_class(name)
            elif kind == "srv":
                cls = get_service_class(name)
            else:
                cls = get_action_class(name)
            text = Text()
            text.append(f"{name}\n\n", style="bold cyan")
            fields = getattr(cls, "get_fields_and_field_types", None)
            if callable(fields):
                for fname, ftype in fields().items():
                    text.append(f"{ftype:30s} ", style="yellow")
                    text.append(f"{fname}\n", style="white")
            else:
                text.append(repr(cls))
            self.query_one("#iface-detail", Static).update(text)
            self.query_one("#iface-header", Static).update(Text(name, style="bold cyan"))
        except Exception as e:
            self.query_one("#iface-detail", Static).update(
                Text(f"could not load {name}: {e}", style="red")
            )
