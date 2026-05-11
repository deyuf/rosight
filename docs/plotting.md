# Plotting deep-dive

The Plot panel is the headline feature: live, multi-series, terminal-native
plotting of any numeric field exposed by any subscribed topic.

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
