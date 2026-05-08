"""Vim-style ``:command`` palette."""

from __future__ import annotations

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import Input, Static


@dataclass
class CommandSubmitted(Message):
    text: str


class CommandPalette(ModalScreen[str | None]):
    """Modal that captures a single command line."""

    BINDINGS = [("escape", "dismiss(None)", "cancel")]

    DEFAULT_CSS = """
    CommandPalette {
        align: center top;
    }
    CommandPalette > Vertical {
        width: 80%;
        max-width: 100;
        margin-top: 4;
        background: $panel;
        border: round $primary;
        padding: 1 2;
    }
    CommandPalette Input {
        border: none;
    }
    CommandPalette .hint {
        color: $text-muted;
    }
    """

    HINT = (
        ":topic <name>     :node <name>     :param <node> <name>     :plot <topic> <path>"
        "\n:pub <topic> <type> <yaml>     :record <topic...>     :quit"
    )

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(":", classes="hint")
            yield Input(placeholder="type a command…", id="cmd-input")
            yield Static(self.HINT, classes="hint")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)
