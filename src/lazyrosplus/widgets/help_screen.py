"""Modal help overlay."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static

HELP_TEXT = """\
# LazyrosPlus — keyboard reference

| key | action |
|-----|--------|
| `q` / `ctrl+c` | quit |
| `?` | toggle this help |
| `:` | command palette |
| `/` | filter current panel |
| `r` | refresh discovery |
| `tab` / `shift+tab` | cycle focus |
| `1`-`9` | switch panel |

## Topics
| key | action |
|-----|--------|
| `enter` | echo (subscribe) selected topic |
| `i` | topic info & QoS endpoints |
| `h` | hz monitor |
| `b` | bandwidth monitor |
| `P` | publish (form) |
| `space` | pause / resume echo |

## Plot
| key | action |
|-----|--------|
| `p` | add highlighted leaf to plot |
| `space` | pause / resume |
| `+` / `-` | extend / shrink time window |
| `c` | clear all series |
| `l` | toggle legend |
| `s` | export CSV |

## Parameters
| key | action |
|-----|--------|
| `g` | get value |
| `s` | set value (form) |
| `y` | yank YAML to clipboard |

## Bags
| key | action |
|-----|--------|
| `R` | start/stop record |
| `p` | play |
| `i` | bag info |

## Command palette ( `:` )
| command | action |
|---------|--------|
| `topic <filter>` | jump to Messages and set filter |
| `plot <topic> <field>` | add series to plot |
| `record` | jump to Bags |
| `domain <N>` | restart rclpy on ROS_DOMAIN_ID `N` (0..232) |
| `quit` | exit the app |
"""


class HelpScreen(ModalScreen[None]):
    """A modal screen showing keyboard help."""

    BINDINGS = [
        ("escape", "dismiss", "close"),
        ("q", "dismiss", "close"),
        ("?", "dismiss", "close"),
    ]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    HelpScreen > VerticalScroll {
        width: 80%;
        height: 80%;
        max-width: 100;
        max-height: 40;
        background: $panel;
        border: round $primary;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("Help", id="help-title")
            yield Markdown(HELP_TEXT)
            with Center():
                yield Static("[esc] to close", classes="dim")
