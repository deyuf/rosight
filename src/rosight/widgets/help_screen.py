"""Modal help overlay."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static

HELP_TEXT = """\
# Rosight — keyboard reference

## Global
| key | action |
|-----|--------|
| `q` / `ctrl+c` | quit (asks first while a bag records or plays) |
| `?` | toggle this help |
| `:` | command palette (→ accepts completion, ↑/↓ history) |
| `/` | filter the current panel (fuzzy: `odm` matches `/odom`) |
| `r` | rediscover the ROS graph now |
| `1`-`9` | switch panel |
| `j` / `k` / `g` / `G` | down / up / first / last (when `ui.vim_keys = true`) |
| `tab` / `shift+tab` | cycle focus |

## Messages (1)
| key | action |
|-----|--------|
| `enter` | subscribe (● marks subscribed topics) and focus the message tree |
| `x` | unsubscribe |
| `i` | topic info & publisher QoS |
| `v` | image preview (Image / CompressedImage) |
| `P` | publish once (YAML form, pre-filled from the last message) |
| `space` | pause / resume the echo |
| `[` / `]` | while paused: older / newer message from the history |
| `esc` | close the field search box |

## Message tree
| key | action |
|-----|--------|
| `enter` | expand; numeric leaf → plot; numeric array → snapshot plot |
| `p` | plot the highlighted field |
| `/` | search fields by path; `n` / `N` next / previous match |
| `y` / `Y` | copy field path / value |

Changed values flash for a moment.

## Nodes (2)
| key | action |
|-----|--------|
| `enter` | show endpoints; `enter` on an endpoint jumps to that topic / service |

## Services (3)
| key | action |
|-----|--------|
| `enter` | inspect |
| `c` | call (YAML request form; the response is shown in the detail) |

## Actions (4)
| key | action |
|-----|--------|
| `enter` | inspect |
| `g` | send a goal (YAML form; live feedback and result) |
| `x` | cancel the running goal |

## Params (5)
| key | action |
|-----|--------|
| `enter` | load the node's parameters |
| `g` | reload |
| `s` | set the highlighted value (type-checked) |
| `y` | copy all parameters as a ROS 2 params YAML file |

## Plot (6)
| key | action |
|-----|--------|
| `space` | pause / resume |
| `+` / `-` | extend / shrink time window |
| `c` | clear all series |
| `l` | toggle legend |
| `d` | delete the highlighted series |
| `s` | export CSV (to `ui.export_dir`) |

## TF (7)
| key | action |
|-----|--------|
| `r` | redraw tree |

## Bags (8)
| key | action |
|-----|--------|
| `R` | start / stop recording |
| `p` | play (stops a previous playback) |
| `s` | stop |
| `i` | bag info |

## Interfaces (9)
| key | action |
|-----|--------|
| `enter` | show definition |

## Image preview
| key | action |
|-----|--------|
| `space` | pause / resume rendering |
| `m` | cycle colormap (turbo → viridis → gray) for depth |
| `s` | save the current frame as PNG (to `ui.export_dir`) |
| `q` / `esc` | close |

## Forms (publish / call / goal / set)
| key | action |
|-----|--------|
| `ctrl+s` | send |
| `esc` | cancel |

## Command palette ( `:` )
| command | action |
|---------|--------|
| `topic <filter>` | jump to Messages and set the filter |
| `node <name>` | jump to that node and show its endpoints |
| `param <node>` | load that node's parameters |
| `plot <topic> <field>` | add a scalar series and show the plot |
| `plot-array <topic> <field>` | add a 1D-array snapshot series |
| `view <topic>` | image preview |
| `unsub <topic>` / `unsub all` | unsubscribe |
| `record` | jump to Bags |
| `domain <N>` | restart on ROS_DOMAIN_ID `N` (0..232) |
| `reconnect` | restart the ROS backend (e.g. after the executor stopped) |
| `help` | this screen |
| `quit` | exit |

Last tab, filters, plot series and command history are restored on the next start.
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
            yield Markdown(HELP_TEXT)
            with Center():
                yield Static("[esc] to close", classes="dim")
