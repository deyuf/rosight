"""Persistent bottom status bar."""

from __future__ import annotations

import os

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static


class StatusBar(Static):
    """Bottom status bar with discovery counters and ROS settings."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $primary 30%;
        color: $text;
        padding: 0 1;
    }
    """

    topics: reactive[int] = reactive(0)
    nodes: reactive[int] = reactive(0)
    services: reactive[int] = reactive(0)
    actions: reactive[int] = reactive(0)
    subs: reactive[int] = reactive(0)
    # ``None`` means "show whatever the env var says" — used before the
    # backend reports an effective domain. The app pushes the real value
    # from ``RosBackend.domain_id`` once the backend is up so the bar
    # reflects ``:domain N`` runtime switches.
    domain_id: reactive[int | None] = reactive(None)
    backend_ok: reactive[bool] = reactive(False)
    message: reactive[str] = reactive("")

    def render(self) -> Text:
        text = Text()
        if self.backend_ok:
            text.append(" ● ", style="bold green")
            text.append("ros ", style="dim")
        else:
            text.append(" ● ", style="bold red")
            text.append("no ros ", style="dim")
        if self.domain_id is not None:
            shown = str(self.domain_id)
        else:
            shown = os.environ.get("ROS_DOMAIN_ID", "0")
        text.append(f"DOMAIN_ID={shown}  ", style="dim")
        text.append(f"topics={self.topics} ", style="cyan")
        text.append(f"nodes={self.nodes} ", style="magenta")
        text.append(f"srv={self.services} ", style="yellow")
        text.append(f"act={self.actions} ", style="green")
        text.append(f"subs={self.subs} ", style="bright_blue")
        if self.message:
            text.append("  ")
            text.append(self.message, style="bold")
        return text
