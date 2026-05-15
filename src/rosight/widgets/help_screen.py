"""Modal help overlay."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static

HELP_TEXT = """\
# Rosight — keyboard reference

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
| `v` | view image preview (sensor_msgs/Image, CompressedImage) |
| `P` | publish (form) |
| `space` | pause / resume echo |

## Message tree (inside Topics)
| key | action |
|-----|--------|
| `p` | plot selected numeric field |
| `enter` | scalar leaf → plot, numeric array → snapshot plot, else expand |

## Plot
| key | action |
|-----|--------|
| `p` | add highlighted leaf to plot |
| `space` | pause / resume |
| `+` / `-` | extend / shrink time window |
| `c` | clear all series |
| `l` | toggle legend |
| `s` | export CSV (time + snapshot series) |

## Image preview (modal)
| key | action |
|-----|--------|
| `space` | pause / resume rendering |
| `m` | cycle colormap (turbo → viridis → gray) for depth |
| `s` | save current frame as PNG to cwd |
| `q` / `esc` | close |

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
| `plot <topic> <field>` | add scalar series to plot |
| `plot-array <topic> <field>` | add 1D-array snapshot series to plot |
| `view <topic>` | open image preview for an Image / CompressedImage topic |
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
