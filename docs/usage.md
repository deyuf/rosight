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
on the network. Columns: name, type (short form), publisher count,
subscriber count, hz, bandwidth.

- `Enter` — subscribe to the highlighted topic. The right pane will fill
  with a tree view of the latest message.
- `i` — show full QoS details for every publisher endpoint.
- `Space` — pause/resume the live tree refresh.
- `/` — focus the filter box (substring match against name and type).
- `r` — request a discovery refresh.

In the message tree:

- Arrow keys / `j` / `k` to navigate.
- `Enter` or `p` on a numeric leaf — adds it to the **Plot** panel and jumps
  there.

### Nodes (`2`)

Every running node, with namespace. Highlight one to see its publishers,
subscribers, service servers/clients, and action endpoints.

### Services (`3`)

Service list with type. Selecting a service shows a summary; auto-form
calling is on the roadmap.

### Actions (`4`)

Action list with type; goal/feedback monitor on roadmap.

### Parameters (`5`)

Two-pane:

- Left — every node on the graph
- Right — that node's parameters with type and value

Press `Enter` (or `g`) to fetch parameters for the highlighted node.
Set/diff/yank are wired in the command palette and on the roadmap.

### Plot (`6`)

The flagship feature. Each series corresponds to one `(topic, field_path)`
tuple, sampled at the panel's refresh rate.

- `Space` — pause/resume
- `+` / `-` — extend/shrink the time window
- `c` — clear all series
- `l` — toggle legend
- `d` — delete the highlighted series
- `s` — export all series to a timestamped CSV in the current directory

See [the plotting guide](plotting.md) for tips and tricks.

### TF (`7`)

Auto-subscribes to `/tf` and `/tf_static` and renders the frame tree. Use
`r` to redraw on demand.

### Bags (`8`)

Spawns `ros2 bag record` / `ros2 bag play` as child processes:

- `R` — toggle recording (uses the args from the input box; default `-a`)
- `p` — play the bag at the path in the second input
- `s` — stop both processes
- `i` — print bag info to the log file

The TUI deliberately wraps the CLI rather than calling `rosbag2_py`
directly so recordings outlive the TUI process.

### Interfaces (`9`)

Browse `msg`, `srv`, and `action` definitions for every importable ROS 2
interface package on the current Python path.

## Command palette

Press `:` to open a single-line command bar (vim-style). Examples:

```text
:topic /scan        # filter Topics panel
:plot /odom twist.twist.linear.x
:record /odom /scan
:quit
```

Unknown commands surface in the status bar.

## Status bar

The bottom strip shows backend health, `ROS_DOMAIN_ID`, and live counters:
topics, nodes, services, actions and active subscriptions. The most recent
panel notification appears on the right.

## Logging

By default `rosight` does not write anything to stderr (it would corrupt
the TUI). Use `--log-file /tmp/rosight.log` and tail in another terminal
when debugging.
