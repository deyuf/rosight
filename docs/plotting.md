# Plotting deep-dive

The Plot panel is the headline feature: live, multi-series, terminal-native
plotting of any numeric field exposed by any subscribed topic.

## Adding a series

There are three ways:

1. **From the message tree** (Topics panel)
   1. Highlight a topic, press `Enter` to subscribe
   2. Navigate the tree to a numeric leaf (`twist.linear.x`, etc.)
   3. Press `p` (or `Enter`) — the leaf becomes a series and the app
      switches to the Plot panel

2. **From the command palette** (any panel)
   ```text
   :plot /odom twist.twist.linear.x
   ```
   The plotter auto-subscribes if necessary.

3. **Programmatically**
   ```python
   from lazyros.app import LazyrosApp
   ...
   app.add_plot_series("/odom", "twist.twist.linear.x")
   ```

## Field paths

Paths follow a small DSL parsed by `lazyros.utils.path.parse_path`:

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
lazyros-1715169312.csv

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
