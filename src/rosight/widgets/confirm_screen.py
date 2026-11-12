"""Small yes/no modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmScreen(ModalScreen[bool]):
    """Ask a yes/no question; dismisses with True (y / enter) or False."""

    BINDINGS = [
        Binding("y,enter", "answer(True)", "Yes"),
        Binding("n,escape,q", "answer(False)", "No"),
    ]

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical {
        width: auto; max-width: 70; height: auto;
        background: $panel; border: round $warning; padding: 1 2;
    }
    ConfirmScreen #confirm-keys { color: $text-muted; margin-top: 1; }
    """

    def __init__(self, question: str) -> None:
        super().__init__()
        self.question = question

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.question, id="confirm-question")
            yield Static("[y]es / [n]o", id="confirm-keys", markup=False)

    def action_answer(self, yes: bool) -> None:
        self.dismiss(yes)
