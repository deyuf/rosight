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
        dock: bottom;
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
        text.append(f"DOMAIN_ID={os.environ.get('ROS_DOMAIN_ID', '0')}  ", style="dim")
        text.append(f"topics={self.topics} ", style="cyan")
        text.append(f"nodes={self.nodes} ", style="magenta")
        text.append(f"srv={self.services} ", style="yellow")
        text.append(f"act={self.actions} ", style="green")
        text.append(f"subs={self.subs} ", style="bright_blue")
        if self.message:
            text.append("  ")
            text.append(self.message, style="bold")
        return text
