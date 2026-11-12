"""Services panel: discover and call services."""

from __future__ import annotations

import asyncio
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Static

from rosight.utils.formatting import short_type
from rosight.widgets._base import GraphListPanel


class ServicesPanel(GraphListPanel):
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

    TABLE_ID = "srv-table"
    COLUMNS = ("Service", "Type")
    GRAPH_FIELD = "services"
    LIST_METHOD = "list_services"
    CACHE_ATTR = "_svc_cache"
    NOUN = "services"
    REFRESH_SECONDS = 2.0

    def __init__(self) -> None:
        super().__init__()
        # service name -> last request YAML, to pre-fill the next call.
        self._last_request: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Input(placeholder="filter services… (fuzzy)", id="filter")
            yield DataTable(id=self.TABLE_ID, cursor_type="row", zebra_stripes=True)
        with Vertical(id="right"):
            yield Static("Select a service", id="srv-header")
            yield Static("", id="srv-detail")

    def _row_cells(self, item: Any) -> tuple[Any, ...]:
        return (item.name, short_type(item.primary_type))

    def _match_fields(self, item: Any) -> tuple[str, ...]:
        return (item.name, item.primary_type)

    def _on_selected(self) -> None:
        self.action_show()

    def action_show(self) -> None:
        s = next((x for x in self.items if x.name == self.selected), None)
        if s is None:
            return
        text = Text()
        text.append(f"{s.name}\n", style="bold cyan")
        text.append(f"types: {', '.join(s.types)}\n", style="dim")
        text.append("\nPress [c] to call. Auto-form coming soon.", style="italic")
        self.query_one("#srv-detail", Static).update(text)

    def action_call(self) -> None:
        """YAML form for the request, call in a worker, show the response."""
        from rosight.ros.introspection import get_service_class
        from rosight.ros.yaml_msg import MessageYamlError, message_to_yaml, yaml_to_message
        from rosight.widgets.yaml_form import YamlFormScreen

        s = next((x for x in self.items if x.name == self.selected), None)
        if s is None:
            self.app_.notify("no service selected", severity="warning")
            return
        ros = self.ros
        if ros is None or not ros.started:
            self.app_.notify(f"cannot call {s.name}: ROS backend not running", severity="warning")
            return
        try:
            req_cls = get_service_class(s.primary_type).Request
        except Exception as e:
            self.app_.notify(f"cannot load {s.primary_type}: {e}", severity="error")
            return
        text = self._last_request.get(s.name) or message_to_yaml(req_cls())

        def validate(t: str) -> str | None:
            try:
                yaml_to_message(t, req_cls)
            except MessageYamlError as e:
                return str(e)
            return None

        def done(t: str | None) -> None:
            if t is None:
                return
            self._last_request[s.name] = t
            req = yaml_to_message(t, req_cls)
            self.run_worker(self._call(s.name, s.primary_type, req), group="srv-call")

        self.app_.push_screen(
            YamlFormScreen(
                f"Call {s.name}  [{short_type(s.primary_type)}]",
                text,
                hint="request",
                submit_label="Call",
                validate=validate,
            ),
            done,
        )

    async def _call(self, name: str, type_name: str, request: object) -> None:
        from rosight.ros.yaml_msg import message_to_yaml

        ros = self.ros
        if ros is None:
            return
        detail = self.query_one("#srv-detail", Static)
        detail.update(Text(f"calling {name}…", style="italic"))
        try:
            resp = await asyncio.to_thread(ros.call_service, name, type_name, request)
        except Exception as e:
            detail.update(Text(f"✗ call failed: {e}", style="bold red"))
            self.app_.notify(f"{name}: {e}", title="Call", severity="error")
            return
        text = Text()
        text.append(f"{name}\n", style="bold cyan")
        text.append("response:\n", style="bold green")
        text.append(message_to_yaml(resp))
        detail.update(text)
        self.app_.push_status(f"{name} returned")
