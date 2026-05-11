# Keybindings

Rosight ships with a vim-leaning, lazygit-style keymap. Press `?` in the
running app for the same reference.

## Global

| Key | Action |
|-----|--------|
| `q` / `Ctrl+C` | quit |
| `?` | toggle help overlay |
| `:` | command palette (see below) |
| `/` | filter the focused panel |
| `r` | refresh discovery |
| `Tab` / `Shift+Tab` | cycle focus across panes |
| `1`-`9` | switch to panel 1-9 |
| `Ctrl+P` | Textual command palette (theme picker etc.) |

## Command palette ( `:` )

| Command | Action |
|---------|--------|
| `topic <filter>` | jump to Messages and set the filter |
| `plot <topic> <field>` | add a series to the plot directly |
| `record` | jump to Bags |
| `domain <N>` | reconnect rclpy on `ROS_DOMAIN_ID=N` (0..232); subscriptions are cleared |
| `quit` | exit |

## Messages panel (`1`)

| Key | Action |
|-----|--------|
| `Enter` | subscribe to the highlighted topic; focus auto-moves to the message tree |
| `i` | static topic info (types, publishers, subscribers, QoS) shown in the side info area — stays put across refresh ticks |
| `h` | hz monitor (auto-subscribes) |
| `b` | bandwidth monitor (auto-subscribes) |
| `Space` | pause / resume tree refresh |
| `P` | publish (form — planned, shows a toast for now) |
| `/` | filter |

In the message tree:

| Key | Action |
|-----|--------|
| arrows / `Space` | navigate, expand / collapse a sub-message |
| `Enter` | expand a non-leaf; on a leaf, treat like `p` |
| `p` | add the highlighted numeric leaf to the Plot panel (non-numeric → toast) |

## Nodes panel (`2`)

| Key | Action |
|-----|--------|
| `Enter` | show endpoints |
| `/` | filter |

## Services panel (`3`)

| Key | Action |
|-----|--------|
| `Enter` | inspect |
| `c` | call (form — planned, shows a toast for now) |
| `/` | filter |

## Actions panel (`4`)

| Key | Action |
|-----|--------|
| `Enter` | inspect |
| `/` | filter |

## Parameters panel (`5`)

| Key | Action |
|-----|--------|
| `Enter` | load parameters for the highlighted node |
| `g` | get value |
| `/` | filter |

## Plot panel (`6`)

| Key | Action |
|-----|--------|
| `Space` | pause / resume |
| `+` / `=` | grow time window |
| `-` | shrink time window |
| `c` | clear all series |
| `l` | toggle legend |
| `d` | delete highlighted series |
| `s` | export all series to CSV |

## TF panel (`7`)

| Key | Action |
|-----|--------|
| `r` | redraw tree |

## Bags panel (`8`)

While idle the header lists the keys; while recording it switches to
`● recording · press R or s to stop`.

| Key | Action |
|-----|--------|
| `R` | start / stop record |
| `p` | play |
| `s` | stop any running record / play |
| `i` | bag info |

The `ros2 bag` subprocess is launched with `stdin=DEVNULL` and its own session
so keystrokes can't race between the TUI and the recorder.

## Interfaces panel (`9`)

| Key | Action |
|-----|--------|
| `Enter` | show definition |
| `/` | filter |

## Copying text from the terminal

Textual captures the mouse for clicks and scrolls, so a normal mouse drag
doesn't reach your terminal's text selection. To copy on-screen text, hold
your terminal's **bypass modifier** while dragging:

- GNOME Terminal / Konsole / xterm / WSL / Windows Terminal: **Shift**
- macOS Terminal.app / iTerm2: **Option / Alt**
- tmux: `Prefix [` (copy-mode), then `v` / `y`

`Ctrl+C` is bound to **quit** in Rosight, so don't use it for "copy".

## Customisation

Keymaps are not yet user-configurable — the design will follow Textual's
binding inheritance once the action surface stabilises. Track the
[development guide](development.md) for the schema.
