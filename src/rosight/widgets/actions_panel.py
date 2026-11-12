"""Actions panel: list ROS 2 actions."""

from __future__ import annotations

import asyncio
import threading
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
        Binding("g", "send_goal", "Send goal"),
        Binding("x", "cancel_goal", "Cancel goal"),
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

    def __init__(self) -> None:
        super().__init__()
        self._last_goal: dict[str, str] = {}
        self._cancel: threading.Event | None = None
        self._running_goal: str | None = None

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
        self.query_one("#act-header", Static).update(Text(a.name, style="bold cyan"))
        text = Text()
        text.append(f"types: {', '.join(a.types)}\n", style="dim")
        if self._running_goal == a.name:
            text.append("\ngoal running — x to cancel", style="yellow")
        else:
            text.append("\ng: send goal", style="italic dim")
        self.query_one("#act-detail", Static).update(text)

    def action_send_goal(self) -> None:
        from rosight.ros.introspection import get_action_class
        from rosight.ros.yaml_msg import MessageYamlError, message_to_yaml, yaml_to_message
        from rosight.widgets.yaml_form import YamlFormScreen

        a = next((x for x in self.items if x.name == self.selected), None)
        if a is None:
            self.app_.notify("no action selected", severity="warning")
            return
        if self._running_goal is not None:
            self.app_.notify(
                f"a goal on {self._running_goal} is still running (x cancels)",
                severity="warning",
            )
            return
        ros = self.ros
        if ros is None or not ros.started:
            self.app_.notify("cannot send goal: ROS backend not running", severity="warning")
            return
        try:
            goal_cls = get_action_class(a.primary_type).Goal
        except Exception as e:
            self.app_.notify(f"cannot load {a.primary_type}: {e}", severity="error")
            return
        text = self._last_goal.get(a.name) or message_to_yaml(goal_cls())

        def validate(t: str) -> str | None:
            try:
                yaml_to_message(t, goal_cls)
            except MessageYamlError as e:
                return str(e)
            return None

        def done(t: str | None) -> None:
            if t is None:
                return
            self._last_goal[a.name] = t
            goal = yaml_to_message(t, goal_cls)
            self.run_worker(self._run_goal(a.name, a.primary_type, goal), group="goal")

        self.app_.push_screen(
            YamlFormScreen(
                f"Goal for {a.name}  [{short_type(a.primary_type)}]",
                text,
                hint="goal",
                submit_label="Send",
                validate=validate,
            ),
            done,
        )

    def action_cancel_goal(self) -> None:
        if self._cancel is None or self._running_goal is None:
            self.app_.push_status("no goal running")
            return
        self._cancel.set()
        self.app_.push_status(f"cancel requested for {self._running_goal}")

    async def _run_goal(self, name: str, type_name: str, goal: object) -> None:
        from rosight.ros.backend import GOAL_STATUS
        from rosight.ros.yaml_msg import message_to_yaml

        detail = self.query_one("#act-detail", Static)
        state: dict[str, object] = {"phase": "sending goal…", "feedback": None}

        self.query_one("#act-header", Static).update(Text(name, style="bold cyan"))

        def render() -> None:
            text = Text()
            text.append(f"{state['phase']}  (x: cancel)\n", style="yellow")
            if state["feedback"] is not None:
                text.append("\nfeedback:\n", style="bold")
                text.append(message_to_yaml(state["feedback"]))
            detail.update(text)

        def on_accepted() -> None:
            state["phase"] = "goal accepted, running…"
            self.app.call_from_thread(render)

        def on_feedback(fb: object) -> None:
            state["feedback"] = fb
            self.app.call_from_thread(render)

        ros = self.ros
        if ros is None:
            return
        self._cancel = threading.Event()
        self._running_goal = name
        render()
        try:
            status, result = await asyncio.to_thread(
                ros.run_action_goal,
                name,
                type_name,
                goal,
                on_feedback=on_feedback,
                on_accepted=on_accepted,
                cancel=self._cancel,
            )
        except Exception as e:
            detail.update(Text(f"✗ goal failed: {e}", style="bold red"))
            self.app_.notify(f"{name}: {e}", title="Action", severity="error")
            return
        finally:
            self._running_goal = None
            self._cancel = None
        label = GOAL_STATUS.get(status, str(status))
        text = Text()
        text.append(f"{label}\n", style="bold green" if status == 4 else "bold red")
        text.append("\nresult:\n", style="bold")
        text.append(message_to_yaml(result))
        detail.update(text)
        self.app_.push_status(f"{name}: goal {label}")
