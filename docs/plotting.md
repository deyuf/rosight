# Plotting deep-dive

The Plot panel is the headline feature: live, multi-series, terminal-native
plotting of any numeric field exposed by any subscribed topic.

Three flavours coexist in the same tab:

- **Scalar time-series** — pick a numeric leaf field (e.g.
  `twist.linear.x`); plotted as Y-vs-time on a scrolling window.
- **1D-array snapshot** — pick a numeric array field (e.g.
  `ranges` from a `sensor_msgs/LaserScan`); plotted as Y-vs-index, the
  latest frame on every refresh.
- **Image preview** — for `sensor_msgs/Image` / `CompressedImage` topics,
  press **v** in the Topics tab to open a modal preview (see
  [Images](#images-rgb-depth-compressed) below).

## Adding a series — the workflow

The Plot panel **does not** auto-plot every subscribed topic; it plots
specific numeric *fields* you pick. Three ways:

1. **From the message tree** (Messages tab) — most common
   1. Move the cursor over a topic in the table.
   2. **Enter** → subscribe to it. Focus auto-jumps to the message tree
      on the right.
   3. Use arrow keys / Space to expand sub-messages (`pose` →
      `position` → `x`).
   4. Cursor on a *numeric* leaf (int / float), press **p** — the series
      is added and the Plot tab opens.
      - If the leaf isn't numeric (string, array, etc.) you get a toast:
        `field <path> is not numeric — skipped`.

2. **From the command palette** (any tab)
   ```text
   :plot /odom twist.twist.linear.x
   ```
   The plotter auto-subscribes if necessary.

3. **Programmatically**
   ```python
   from rosight.app import RosightApp
   ...
   app.add_plot_series("/odom", "twist.twist.linear.x")
   ```

> **Stuck on "no series — press \[p] in the message tree to add a field"?**
> That hint is correct: until you walk the tree to a numeric leaf and
> press `p`, the chart stays empty even if you have data flowing. See
> [keybindings](keybindings.md#messages-panel-1) for the full path.

## Field paths

Paths follow a small DSL parsed by `rosight.utils.path.parse_path`:

- Dotted attributes: `pose.position.x`
- Sequence index: `poses[3].position.x`
- Mix of both: `joint_states.position[5]`

A leading slash is tolerated (`/twist.linear.x`). Booleans are plotted as
0/1.

## Time window

The X axis is "seconds from now" — a moving window that scrolls left as
new samples arrive. Adjust at runtime with `+` and `-`; values are
clamped between 1 s and 600 s.

The plotter uses a `TimedRingBuffer` per series with a max-points cap so
high-frequency topics do not blow up memory:

```
window_seconds = 30        # default; configurable
max_points     = 5000      # default; configurable
```

When the window shrinks, older points are evicted on the next sample.

## Pause and inspect

`Space` freezes the plot. The buffer keeps growing in the background, but
the chart stops scrolling so you can read values precisely.

## Stats and legend

When the legend is enabled (`l` toggles), each series shows the latest
value next to its colour swatch. The side table shows truncated labels and
the most recent reading at 1 Hz.

## Exporting

Press `s` to dump every series in the buffer to a CSV in the current
directory:

```
rosight-1715169312.csv

timestamp,label,value
12345.123,/odom/twist.twist.linear.x,0.182
12345.143,/odom/twist.twist.linear.x,0.184
...
```

`timestamp` is `time.monotonic` seconds since process start — relative,
not wall-clock.

## Performance tips

- Plotting many series at very high rates (>1 kHz) is fine but consumes
  CPU on each redraw. The plotter throttles to ~15 Hz internally.
- If the chart looks empty, the field is probably non-numeric or the
  topic has no live publisher — check the Topics panel.
- For long captures, consider exporting CSV and post-processing in pandas
  rather than holding huge buffers in memory.

## 1D-array snapshot plotting

Pick a numeric *array* field — e.g. `ranges` on `sensor_msgs/LaserScan`,
`position` on `sensor_msgs/JointState`, `data` on `std_msgs/Float64MultiArray`
— and the plotter shows the whole array as a value-vs-index curve, refreshed
every frame.

How to add:

1. Subscribe (`Enter`) to the topic in the Topics tab.
2. In the message tree, navigate to the array field. Numeric arrays show
   the `<N items>` marker plus a green `[plot ↵]` hint.
3. Press **Enter** (or `p`) on the array node.

Or use the command palette:

```text
:plot-array /scan ranges
```

The Plot tab shows:

- **One kind only** — single chart, X axis is array index.
- **Mixed time-series and snapshot** — two stacked subplots, top is
  time-series (X = seconds-from-now), bottom is snapshot (X = index).
- The side table lists each series; snapshot rows show `n=N [min…max]`.
- CSV export writes a `kind` column distinguishing `time` and `snapshot`
  rows so post-processing in pandas can split them.

Caps: arrays longer than 4096 elements are truncated to the first 4096
points (so an Image's `data` array still draws — just not very usefully).

## Images: RGB, depth, compressed

For `sensor_msgs/Image` or `sensor_msgs/CompressedImage` topics, press
**v** in the Topics tab to open a modal preview. Supported encodings:

| encoding | rendering |
|----------|-----------|
| `rgb8`, `bgr8`, `rgba8`, `bgra8` | direct color |
| `mono8` | grayscale |
| `mono16` | normalized → false-color colormap |
| `32FC1` | depth in metres → normalized → colormap; NaN/Inf masked |
| jpeg / png (CompressedImage) | Pillow decodes (sniffs magic bytes) |

Inside the modal:

- **space** — pause / resume rendering
- **m** — cycle colormap (turbo → viridis → gray) for depth-like images
- **s** — save the current frame as a PNG in the working directory
- **q** / **esc** — close

Rendering throttles to ~5 Hz regardless of publish rate.

### Terminal protocol fallback

`textual-image` auto-detects what the terminal supports:

| terminal | rendering |
|----------|-----------|
| Kitty, WezTerm, foot | Kitty graphics protocol (pixel-perfect) |
| iTerm2, xterm with sixel, Windows Terminal | Sixel |
| anything else (xterm, screen, stripped tmux) | Unicode half-block (visible but pixelated) |

Inside `tmux`, you need `set -g allow-passthrough on` (tmux ≥ 3.3) and a
graphics-capable inner terminal for the pixel protocols to work; otherwise
you'll see the half-block fallback automatically.

### Plotting array fields *of* image messages

You *can* press Enter on an `Image.data` field — the snapshot plotter will
draw the first 4096 raw bytes as a line. That's almost never what you
want; use **v** on the topic itself instead.
