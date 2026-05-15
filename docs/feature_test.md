# Manual feature test matrix — array snapshots & image preview

This document captures the end-to-end test plan for the array-snapshot
plotting and image-preview features. The automated tests in
`tests/test_array_snapshot.py` and `tests/test_image_decode.py` cover the
core data path, but the visible behavior in a real terminal can only be
verified by hand.

Re-run this matrix whenever any of these files change:

- `src/rosight/widgets/plot_view.py`
- `src/rosight/widgets/plot_panel.py`
- `src/rosight/widgets/image_screen.py`
- `src/rosight/utils/image_decode.py`
- `src/rosight/widgets/topics_panel.py`
- `src/rosight/widgets/message_tree.py`
- `src/rosight/ros/introspection.py`

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
ruff check src tests
mypy src             # bags_panel Popen overloads are pre-existing
python -m pytest -q  # 112+ passed expected
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
| B2 | On `ranges` press `Enter` | Switches to Plot tab; chart updates at ~15 Hz, X axis 0..359. |
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
| C2 | Press `s` | `rosight-camera_image_raw-<ts>.png` saved to cwd. Open it. |
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

## Reporting

Record failures in `--log-file rosight.log` and attach to the PR. If a test
fails because of a terminal protocol limitation (e.g. unicode-block fallback
looks bad), that's documented behavior — note the terminal in the PR but
don't gate the merge on it.
