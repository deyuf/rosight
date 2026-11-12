# Keybindings

Rosight ships with a vim-leaning, lazygit-style keymap. Press `?` in the
running app for the same reference; a test keeps the in-app help and the
real bindings in sync.

## Global

| Key | Action |
|-----|--------|
| `q` / `Ctrl+C` | quit — asks for confirmation while a bag is recording or playing |
| `?` | toggle help overlay |
| `:` | command palette (see below) |
| `/` | filter the focused panel (fuzzy: `odm` matches `/odom`, several words must all match) |
| `r` | rediscover the ROS graph immediately |
| `Tab` / `Shift+Tab` | cycle focus across panes |
| `1`-`9` | switch to panel 1-9 |
| `j` / `k` / `g` / `G` | down / up / first / last in the focused table or tree (`ui.vim_keys = true`, the default) |
| `Ctrl+P` | Textual command palette (theme picker etc.) |

Panel keys take precedence over the global vim motions, so `g` in the
Actions and Params panels keeps its panel meaning.

## Command palette ( `:` )

Completion is shown as ghost text — `→` accepts it. Command names, topic
names and plottable field paths of the topic's message type are completed.
`↑` / `↓` walk the history (kept across restarts).

| Command | Action |
|---------|--------|
| `topic <filter>` | jump to Messages and set the filter |
| `node <name>` | jump to that node (`talker` or `/ns/talker`) and show its endpoints |
| `param <node>` | open Params and load that node's parameters |
| `plot <topic> <field>` | add a scalar time-series and show the plot |
| `plot-array <topic> <field>` | add a 1D-array snapshot series |
| `view <topic>` | open the image preview for an Image / CompressedImage topic |
| `unsub <topic>` / `unsub all` | drop subscriptions |
| `record` | jump to Bags |
| `domain <N>` | reconnect on `ROS_DOMAIN_ID=N` (0..232); subscriptions are cleared, plotted topics resubscribe automatically |
| `reconnect` | restart the ROS backend (offered when the executor thread stops) |
| `help` | this reference |
| `quit` | exit |

## Messages panel (`1`)

| Key | Action |
|-----|--------|
| `Enter` | subscribe to the highlighted topic (● marks subscribed rows); focus moves to the message tree |
| `x` | unsubscribe (warns if plot series use the topic) |
| `i` | static topic info (types, publishers, subscribers, QoS) in the side info area |
| `v` | image preview modal (`sensor_msgs/Image` / `CompressedImage`) |
| `P` | publish once — YAML form pre-filled from the last received message (or defaults) |
| `Space` | pause / resume the echo |
| `[` / `]` | while paused: step to an older / newer message (last 100 messages, 16 MB max) |
| `Esc` | close the field search box |

The table's **Trend** column is a sparkline of the last 12 s of Hz. If the
publisher's QoS is incompatible with ours, the Hz cell shows `QoS!` and the
detail header names the policy.

In the message tree:

| Key | Action |
|-----|--------|
| arrows / `Space` | navigate, expand / collapse a sub-message |
| `Enter` | expand a non-leaf; numeric leaf → time-series plot; numeric **array** (`[plot ↵]`) → snapshot plot |
| `p` | add the highlighted field to the plot (you stay on this tab) |
| `/` | search fields by path; `n` / `N` jump to the next / previous match |
| `y` / `Y` | copy the field path / value to the clipboard (OSC 52) |

Values that changed since the previous message flash briefly.

## Nodes panel (`2`)

| Key | Action |
|-----|--------|
| `Enter` | show the node's endpoints as a tree |
| `Enter` on an endpoint | jump to that topic / service / action |

## Services panel (`3`)

| Key | Action |
|-----|--------|
| `Enter` | inspect |
| `c` | call — YAML request form (remembers your last request); the response is shown as YAML |

## Actions panel (`4`)

| Key | Action |
|-----|--------|
| `Enter` | inspect |
| `g` | send a goal — YAML form; live feedback and the final status / result in the detail pane |
| `x` | cancel the running goal |

## Parameters panel (`5`)

| Key | Action |
|-----|--------|
| `Enter` | load parameters for the highlighted node |
| `g` | reload |
| `s` | set the highlighted value (type-checked; arrays supported) |
| `y` | copy all parameters as a ROS 2 params YAML file |

## Plot panel (`6`)

| Key | Action |
|-----|--------|
| `Space` | pause / resume |
| `+` / `=` | grow time window |
| `-` | shrink time window |
| `c` | clear all series |
| `l` | toggle legend |
| `d` | delete highlighted series |
| `s` | export all series to CSV in `ui.export_dir` (`kind` column distinguishes time vs snapshot) |

When the panel has both scalar and snapshot series, the chart splits into
two stacked subplots: time-series on top (X = seconds-from-now), snapshot
on the bottom (X = array index). See [plotting deep-dive](plotting.md).

## Image preview modal (over Topics, opened with `v`)

| Key | Action |
|-----|--------|
| `Space` | pause / resume rendering (decode stays cached) |
| `m` | cycle colormap for depth (`turbo` → `viridis` → `gray`); ignored for color/compressed |
| `s` | save the current frame as `rosight-<topic>-<ts>.png` in `ui.export_dir` |
| `q` / `Esc` | close (releases the subscription if the preview created it) |

## Forms (publish / call / goal / parameter)

| Key | Action |
|-----|--------|
| `Ctrl+S` | send (invalid YAML, unknown fields or wrong types are shown inline) |
| `Esc` | cancel |

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
| `p` | play (a previous playback is stopped first) |
| `s` | stop any running record / play |
| `i` | bag info |

The `ros2 bag` subprocess runs in its own session with `stdin=DEVNULL`, so
keystrokes can't race between the TUI and the recorder. Stopping sends
SIGINT (so rosbag2 finalizes `metadata.yaml`), escalating to SIGTERM /
SIGKILL; children are always stopped when Rosight exits.

## Interfaces panel (`9`)

| Key | Action |
|-----|--------|
| `Enter` | show definition |
| `/` | filter |

## What Rosight remembers

`state.toml` (next to `config.toml`) keeps the theme, last tab, every
panel's filter, the plot series and the command history. Plot series
resubscribe automatically once their topics are discovered.

## Copying text from the terminal

Use `y` / `Y` in the message tree and `y` in Params to copy through the
terminal (OSC 52, works over SSH in most terminals). For arbitrary
on-screen text, hold your terminal's **bypass modifier** while dragging:

- GNOME Terminal / Konsole / xterm / WSL / Windows Terminal: **Shift**
- macOS Terminal.app / iTerm2: **Option / Alt**
- tmux: `Prefix [` (copy-mode), then `v` / `y`

`Ctrl+C` is bound to **quit** in Rosight, so don't use it for "copy".

## Customisation

Keymaps are not yet user-configurable — the design will follow Textual's
binding inheritance once the action surface stabilises. Track the
[development guide](development.md) for the schema.
