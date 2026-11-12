# Usage guide

## Launching

```bash
rosight [--config PATH] [--domain-id N] [--no-ros] [--log-level LEVEL] [--log-file FILE]
```

Most-used flags:

| Flag | Description |
|------|-------------|
| `--domain-id N` | Override `ROS_DOMAIN_ID` for this run |
| `--no-ros` | Start without bringing up rclpy (UI testing, screenshots) |
| `--log-file PATH` | Write detailed logs to a file (recommended in production) |
| `-c, --config PATH` | Override config TOML location |

Press `?` once running for a complete keyboard reference.

## Tour of the panels

The top tab strip shows all panels. Switch with `Tab` / `Shift+Tab` or
number keys `1`-`9`.

### Topics (`1`)

The headline panel. Left: a scrolling list of every topic currently visible
on the network. Columns: name (● = subscribed), type (short form),
publisher count, subscriber count, Hz, bandwidth per second, and an Hz
**trend** sparkline of the last 8 s. `QoS!` in the Hz column means the
publisher's QoS is incompatible with ours; the detail header names the
policy.

- `Enter` — subscribe to the highlighted topic. The right pane fills with a
  tree view of the latest message and focus moves there.
- `x` — unsubscribe (frees the bandwidth / CPU of that topic).
- `i` — show full QoS details for every publisher endpoint.
- `P` — publish once: a YAML form pre-filled from the last received message
  (or the type's defaults); `ctrl+s` sends, `esc` cancels.
- `Space` — pause/resume the live tree. While paused, `[` / `]` step to
  older / newer messages (the last 100, 16 MB at most).
- `/` — focus the filter box (fuzzy: `odm` matches `/odom`).
- `r` — rediscover the graph immediately.

In the message tree:

- Arrow keys / `j` / `k` to navigate; values that changed since the last
  message flash briefly.
- `/` — search fields by path; `n` / `N` next / previous match.
- `y` / `Y` — copy the field path / value to the clipboard.
- `Enter` or `p` on a numeric leaf — adds it to the **Plot** panel; you stay
  in the tree to add more.
- `Enter` on a numeric array container (look for the green `[plot ↵]`
  marker, e.g. `ranges` on a LaserScan) — plots the array as a
  value-vs-index snapshot in the Plot panel.

Additional Topics-level keys:

- `v` on a `sensor_msgs/Image` or `sensor_msgs/CompressedImage` topic —
  opens the image preview modal (RGB / depth-colormapped / decoded JPEG/PNG).
  Inside the modal: `space` pause, `m` cycle colormap, `s` save PNG, `q`/`Esc`
  close.

### Nodes (`2`)

Every running node, with namespace. Highlight one to see its publishers,
subscribers and service servers/clients as a tree; `Enter` on an entry
jumps to that topic or service (clearing any filter in the way).
`:node <name>` selects a node from anywhere.

### Services (`3`)

Service list with type. `c` opens a YAML form pre-filled with the
request's fields (or the last request you sent); `ctrl+s` calls it in the
background and the response is shown as YAML in the detail pane.

### Actions (`4`)

Action list with type. `g` opens a YAML goal form; once sent, the detail
pane shows acceptance, live feedback and the final status and result.
`x` cancels the running goal.

### Parameters (`5`)

Two-pane:

- Left — every node on the graph
- Right — that node's parameters with type and value

Press `Enter` (or `g`) to fetch parameters for the highlighted node
(`:param <node>` does the same from anywhere). `s` edits the highlighted
value — the new value is type-checked against the parameter's declared
type, arrays included — and `y` copies all parameters as a ROS 2
params file (`<node>: ros__parameters: …`).

### Plot (`6`)

The flagship feature. Two kinds of series coexist:

- **Scalar time-series** — one `(topic, field_path)` tuple, sampled at the
  panel's refresh rate; X axis is seconds-from-now.
- **1D-array snapshot** — the latest frame of a numeric array
  (LaserScan ranges, JointState positions, etc.); X axis is array index.

When both kinds are present the chart splits into two stacked subplots.

Keys:

- `Space` — pause/resume
- `+` / `-` — extend/shrink the time window
- `c` — clear all series
- `l` — toggle legend
- `d` — delete the highlighted series
- `s` — export all series to a timestamped CSV (column `kind` is
  `time` or `snapshot`)

See [the plotting guide](plotting.md) for array snapshots, image previews
and terminal-protocol notes.

### TF (`7`)

Auto-subscribes to `/tf` and `/tf_static` and renders the frame tree. Use
`r` to redraw on demand.

### Bags (`8`)

Spawns `ros2 bag record` / `ros2 bag play` as child processes:

- `R` — toggle recording (uses the args from the input box, parsed like a
  shell command line; default `-a`). Output goes to `ui.bag_output_dir`,
  else `ui.export_dir`, else the current directory.
- `p` — play the bag at the path in the second input (a running playback
  is stopped first; missing paths are reported instead of launched)
- `s` — stop both processes
- `i` — print bag info to the log file

The TUI wraps the `ros2 bag` CLI rather than calling `rosbag2_py`
directly. Stopping sends `SIGINT` (so rosbag2 writes `metadata.yaml`),
escalating to `SIGTERM` / `SIGKILL`; children are always stopped when
Rosight exits, and quitting while recording asks for confirmation first.

### Interfaces (`9`)

Browse `msg`, `srv`, and `action` definitions for every importable ROS 2
interface package on the current Python path.

## Command palette

Press `:` to open a single-line command bar (vim-style). Examples:

```text
:topic /scan        # filter Topics panel
:plot /odom twist.twist.linear.x
:plot-array /scan ranges
:view /camera/image_raw
:node planner_server
:param /controller_server
:unsub all
:domain 3
:reconnect
:quit
```

Command names, topic names and plottable field paths are completed as you
type (→ accepts); `↑` / `↓` walk the history, which is kept across
restarts. Unknown commands surface in the status bar. See
[keybindings](keybindings.md#command-palette) for the full list.

## Status bar

The bottom strip shows backend health, `ROS_DOMAIN_ID`, and live counters:
topics, nodes, services, actions and active subscriptions. The most recent
panel notification appears on the right.

## Logging

By default `rosight` does not write anything to stderr (it would corrupt
the TUI). Use `--log-file /tmp/rosight.log` and tail in another terminal
when debugging.
