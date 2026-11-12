"""Vim-style ``:command`` palette with completion and history."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.suggester import Suggester
from textual.widgets import Input, Static

# Commands whose first argument is a topic name.
TOPIC_ARG_COMMANDS = {"topic", "plot", "plot-array", "view", "unsub"}
# Commands whose second argument is a field path of that topic.
FIELD_ARG_COMMANDS = {"plot": False, "plot-array": True}  # value: arrays?


@dataclass
class CommandSubmitted(Message):
    text: str


class CommandSuggester(Suggester):
    """Inline (ghost-text) completion; → or tab accepts.

    * first word: command names
    * topic argument: discovered topic names (``unsub`` also offers ``all``)
    * field argument of ``plot`` / ``plot-array``: plottable field paths of
      that topic's message type
    """

    def __init__(
        self,
        commands: Sequence[str],
        topics: Callable[[], list[str]],
        fields: Callable[[str, bool], list[str]],
    ) -> None:
        super().__init__(use_cache=False, case_sensitive=True)
        self.commands = sorted(commands)
        self.topics = topics
        self.fields = fields

    async def get_suggestion(self, value: str) -> str | None:
        return self.suggest(value)

    def suggest(self, value: str) -> str | None:
        parts = value.split(" ")
        if len(parts) == 1:
            return _complete(value, parts[0], self.commands)
        cmd = parts[0]
        if len(parts) == 2 and cmd in TOPIC_ARG_COMMANDS:
            choices = self.topics() + (["all"] if cmd == "unsub" else [])
            return _complete(value, parts[1], choices)
        if len(parts) == 3 and cmd in FIELD_ARG_COMMANDS:
            return _complete(value, parts[2], self.fields(parts[1], FIELD_ARG_COMMANDS[cmd]))
        return None


def _complete(value: str, prefix: str, choices: Sequence[str]) -> str | None:
    for c in choices:
        if c.startswith(prefix) and c != prefix:
            return value + c[len(prefix) :]
    return None


class CommandPalette(ModalScreen[str | None]):
    """Modal that captures a single command line."""

    BINDINGS = [
        ("escape", "dismiss(None)", "cancel"),
        Binding("up", "history(-1)", "previous", show=False),
        Binding("down", "history(1)", "next", show=False),
    ]

    DEFAULT_CSS = """
    CommandPalette {
        align: center top;
        background: $background 60%;
    }
    CommandPalette > Vertical {
        width: 80%;
        max-width: 100;
        height: auto;
        margin-top: 4;
        background: $panel;
        border: round $primary;
        padding: 1 2;
    }
    CommandPalette Input {
        height: 3;
        background: $surface;
        border: tall $accent;
    }
    CommandPalette .hint {
        color: $text-muted;
        height: auto;
    }
    """

    # One group per line, each short enough not to wrap mid-command at
    # 100 columns.
    HINT = (
        ":topic <filter>   :node <name>   :param <node>   :view <topic>\n"
        ":plot <topic> <field>   :plot-array <topic> <field>\n"
        ":unsub <topic|all>   :domain <N>   :reconnect   :record   :quit\n"
        "→ accept completion · ↑/↓ history · esc close"
    )

    def __init__(
        self,
        history: Sequence[str] = (),
        suggester: Suggester | None = None,
    ) -> None:
        super().__init__()
        self.history = list(history)
        self._hist_pos = len(self.history)
        self._suggester = suggester

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(":", classes="hint")
            yield Input(placeholder="type a command…", id="cmd-input", suggester=self._suggester)
            yield Static(self.HINT, classes="hint", markup=False)

    def action_history(self, step: int) -> None:
        if not self.history:
            return
        self._hist_pos = max(0, min(len(self.history), self._hist_pos + step))
        box = self.query_one("#cmd-input", Input)
        box.value = self.history[self._hist_pos] if self._hist_pos < len(self.history) else ""
        box.cursor_position = len(box.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)
