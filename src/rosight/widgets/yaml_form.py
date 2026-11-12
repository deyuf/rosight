"""Modal YAML editor used for publish / service call / action goal / param set."""

from __future__ import annotations

from collections.abc import Callable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea


class YamlFormScreen(ModalScreen[str | None]):
    """Edit a YAML document and submit it.

    ``validate(text)`` returns an error string (shown inline, form stays
    open) or ``None`` to accept; the screen then dismisses with the text.
    Escape dismisses with ``None``.
    """

    BINDINGS = [
        Binding("ctrl+s", "submit", "Send", priority=True),
        # priority: the TextArea otherwise uses escape to release focus.
        Binding("escape", "cancel", "Cancel", priority=True),
    ]

    DEFAULT_CSS = """
    YamlFormScreen { align: center middle; }
    YamlFormScreen > Vertical {
        width: 90%; max-width: 110; height: 85%;
        background: $panel; border: round $primary; padding: 1 2;
    }
    YamlFormScreen #form-title { text-style: bold; color: $accent; }
    YamlFormScreen #form-hint { color: $text-muted; }
    YamlFormScreen TextArea { height: 1fr; margin: 1 0; }
    YamlFormScreen #form-error { color: $error; height: auto; }
    YamlFormScreen Horizontal { height: auto; align-horizontal: right; }
    YamlFormScreen Button { margin-left: 2; }
    """

    def __init__(
        self,
        title: str,
        text: str,
        *,
        hint: str = "",
        submit_label: str = "Send",
        validate: Callable[[str], str | None] | None = None,
    ) -> None:
        super().__init__()
        self.form_title = title
        self.initial_text = text
        self.hint = hint
        self.submit_label = submit_label
        self.validate = validate

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self.form_title, id="form-title", markup=False)
            yield Static(
                (self.hint + "  ·  " if self.hint else "") + "ctrl+s: send · esc: cancel",
                id="form-hint",
                markup=False,
            )
            yield TextArea(self.initial_text, id="form-text", tab_behavior="indent")
            yield Static("", id="form-error", markup=False)
            with Horizontal():
                yield Button("Cancel", id="form-cancel")
                yield Button(self.submit_label, id="form-submit", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#form-text", TextArea).focus()

    @property
    def text(self) -> str:
        return self.query_one("#form-text", TextArea).text

    def action_submit(self) -> None:
        text = self.text
        error = self.validate(text) if self.validate else None
        if error:
            self.query_one("#form-error", Static).update(f"✗ {error}")
            return
        self.dismiss(text)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "form-submit":
            self.action_submit()
        else:
            self.action_cancel()
