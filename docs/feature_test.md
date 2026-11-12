# Manual feature test matrix

The automated suite drives every panel headless and CI runs it against
real rclpy on Humble and Jazzy, but some behaviour can only be verified
against a live graph in a real terminal: the request/goal/parameter round
trips with real interface types, image protocols, and stress. This page is
the hand-run plan.

Re-run the relevant section whenever these change:

| Section | Files |
|---------|-------|
| B, C, D | `widgets/plot_view.py`, `widgets/plot_panel.py`, `widgets/image_screen.py`, `utils/image_decode.py`, `widgets/message_tree.py`, `ros/introspection.py` |
| E | `ros/yaml_msg.py`, `widgets/yaml_form.py`, `ros/backend.py` (publish / call / goal / parameters) |
| F | `widgets/topics_panel.py`, `widgets/nodes_panel.py`, `widgets/_base.py`, `app.py`, `config.py` |
| G | `ros/backend.py`, `ros/discovery.py`, `widgets/bags_panel.py`, `app.py` |

## Setup

You need a ROS 2 distro (Humble or newer) and a bag that publishes a
laser scan, joint state, RGB camera image, and depth image.
[`turtlebot3_gazebo`](https://github.com/ROBOTIS-GIT/turtlebot3) +
[`realsense2_camera` sample bag](https://github.com/IntelRealSense/realsense-ros)
are convenient sources.

Terminal A:
```bash
source /opt/ros/<distro>/setup.bash
ros2 bag play <path-to-bag> --loop
```

Terminal B:
```bash
source /opt/ros/<distro>/setup.bash
pip install -e ".[dev]"
rosight
```

## Automated baseline

```bash
ruff check src tests && ruff format --check src tests
mypy src/rosight     # one pre-existing error in utils/image_decode.py
python -m pytest -q  # 350+ passed expected (rclpy tests skip without ROS)
```

For sections E–G also start the standard demo servers (Terminal C):

```bash
ros2 run demo_nodes_cpp add_two_ints_server &
ros2 run action_tutorials_cpp fibonacci_action_server &
ros2 run demo_nodes_cpp talker &
ros2 run demo_nodes_cpp listener &
```

## Manual matrix

### A. UI-only (`--no-ros`)

| # | Step | Expected |
|---|------|----------|
| A1 | `rosight --no-ros` | Boots; status bar shows `backend not connected`. |
| A2 | Press `6` | Plot tab shows "no series — press [p]…" hint. |
| A3 | Press `1`, then `v` (no topic selected) | Status: "select a topic first"; no modal. |
| A4 | `:plot-array /foo bar` | Unknown topic; falls through cleanly (no crash). |
| A5 | Press `?` then `Esc` | Help shows new sections "Image preview" and "Message tree". |

### B. With ROS — 1D array snapshot plotting

| # | Step | Expected |
|---|------|----------|
| B1 | Topics → `/scan` Enter | Subscribes; message tree shows `ranges  <360 items>  [plot ↵]`. |
| B2 | On `ranges` press `Enter`, then `6` | Stays in the tree until `6`; Plot chart updates at ~15 Hz, X axis 0..359. |
| B3 | Side table | Row shows `n=360 [min…max]`. |
| B4 | Add a scalar series: `/odom` Enter, `twist.linear.x` `p` | Plot now shows **two stacked subplots** (top time, bottom index). |
| B5 | Press `Space` | Both subplots freeze; `[PAUSED]` banner. |
| B6 | Press `c` | All series clear, "no series" hint returns. |
| B7 | `:plot-array /joint_states position` | Joint position array snapshot is plotted. |
| B8 | Press `s` | CSV written. Open it: header is `kind,x,label,value`; rows tagged `time` or `snapshot`. |
| B9 | Press `d` on a snapshot row | Series is removed. |

### C. With ROS — Image preview

Run in each of these terminals (or as many as you have access to):
- Kitty, WezTerm, or foot (kitty graphics)
- iTerm2 or xterm-with-sixel (sixel)
- Default xterm, gnome-terminal, default tmux (unicode fallback)

| # | Step | Expected |
|---|------|----------|
| C1 | `/camera/image_raw` (rgb8) Enter, then `v` | Modal opens, image visible at ~5 Hz. |
| C2 | Press `s` | `rosight-camera_image_raw-<ts>.png` saved to `ui.export_dir` (default cwd); the toast shows the full path. Open it. |
| C3 | Press `space` | Image freezes; header includes `PAUSED`. |
| C4 | Press `q` | Modal closes; back to Topics; no other panels affected. |
| C5 | `/camera/depth/image_rect_raw` (32FC1) `v` | Depth shown in turbo colormap. |
| C6 | Press `m` | Cycles to viridis; press again → gray; again → turbo. |
| C7 | `/camera/image_raw/compressed` `v` | JPEG/PNG decoded; modal works the same. |
| C8 | Select `/scan` (a non-image topic) press `v` | Status: "/scan is sensor_msgs/msg/LaserScan, not an image topic"; no modal. |
| C9 | `:view /camera/image_raw` | Same as C1. |
| C10 | Modal open, **resize terminal** (drag corner) | Image rescales without crash. |
| C11 | Modal open, then `domain` switch via `:domain 99` (no such domain) | Modal exits cleanly when subscription dies. |

### D. Stress

| # | Step | Expected |
|---|------|----------|
| D1 | Image stream at 30 Hz 1280×720 | CPU usage of `rosight` < 50%; modal renders ~5 Hz; terminal responsive. |
| D2 | Plot 6 scalar + 2 snapshot series at 100 Hz | Chart still updates; no missed redraw warnings in `--log-file`. |
| D3 | Snapshot a huge array (e.g. `Image.data` with `len > 4096`) | Plot truncates to first 4096 points; no memory blow-up. |

### E. With ROS — forms (publish / call / goal / parameters)

| # | Step | Expected |
|---|------|----------|
| E1 | Services → `/add_two_ints`, `c`, set `a: 2`, `b: 40`, `ctrl+s` | Detail shows `response:` `sum: 42`. `c` again pre-fills `a: 2 / b: 40`. |
| E2 | In the form type `a: x` and `ctrl+s` | Inline error (`expects an integer`), form stays open; `esc` closes it. |
| E3 | Actions → `/fibonacci`, `g`, `order: 8`, `ctrl+s` | Detail: `goal accepted, running…`, feedback `partial_sequence` grows, ends `succeeded` with the full sequence. |
| E4 | `g` with `order: 40`, then `x` while running | Ends `canceled`; a second `g` while running is refused with a toast. |
| E5 | Topics → `/chatter` Enter, then `P`, edit `data: hello`, `ctrl+s` | Toast `published to /chatter`; the listener terminal prints `I heard: [hello]`. |
| E6 | Params → `/talker` Enter → highlight `use_sim_time` → `s`, type `true` | Value changes to `True` after the reload. Typing `5` instead is rejected inline (`expected a bool value`). |
| E7 | Params → `y` | Clipboard holds `/talker:` `ros__parameters:` YAML; paste it into a file and `ros2 param load /talker <file>` succeeds. |

### F. Navigation and session

| # | Step | Expected |
|---|------|----------|
| F1 | Nodes → `/listener` → `Enter` on subscriber `/chatter` | Messages tab, cursor on `/chatter`, filter cleared. |
| F2 | With a table focused press `2`, `6`, `1` | Each key switches tab immediately (no bounce back). |
| F3 | `:` then `plot /cha` → `→` | Completes `/chatter`; field paths complete on the third word. `↑` recalls earlier commands. |
| F4 | Subscribe 3 topics, `x` on one | Its ● marker and Hz disappear; others keep updating. `:unsub all` clears the rest. |
| F5 | Filter Services with `atw`, plot `/odom` x, go to Plot, quit with `q`, restart | Same tab, Services filter `atw`, plot series back and receiving once `/odom` is up. |
| F6 | Message tree on `/odom`: collapse `pose`, move cursor to `twist.twist.linear.x` | Changing values flash; collapse state and cursor survive the 4 Hz refresh. `/` `angular` finds the field; `y` copies `twist.twist.angular.z`. |
| F7 | `Space` on `/odom`, then `[` × 5, `]` × 2 | Header shows `⏸ paused · message 96/100 …`; tree shows those older messages. |

### G. Stability

| # | Step | Expected |
|---|------|----------|
| G1 | Bags → `R` (record `-a`), then `q` | Confirmation dialog; `y` quits. `ps aux \| grep "ros2 bag"` shows nothing; the bag has a `metadata.yaml`. |
| G2 | Record, then kill the terminal window | Recorder is stopped (atexit handler). |
| G3 | `:domain 7` with plotted topics on domain 0, then `:domain 0` | UI stays responsive during the switch; plot data resumes after switching back. |
| G4 | Subscribe a topic whose publisher is `RELIABLE` + `TRANSIENT_LOCAL` from a `BEST_EFFORT` launch override | Hz shows `QoS!`; header names the incompatible policy. |
| G5 | 2000-topic graph (e.g. `ros2 run` a topic-flood script) | Tab switches stay instant; status bar counts update once per `discovery_period`. |

## Reporting

Record failures in `--log-file rosight.log` and attach to the PR. If a test
fails because of a terminal protocol limitation (e.g. unicode-block fallback
looks bad), that's documented behavior — note the terminal in the PR but
don't gate the merge on it.
