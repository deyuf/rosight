# Architecture

This page is a tour of the codebase, in the order you'd encounter the
layers when tracing a single keystroke from the user to a ROS message.

```
┌───────────────────────────────────────────────────────────────┐
│  Keyboard                                                     │
│     │                                                         │
│     ▼                                                         │
│  Textual main loop (asyncio)                                  │
│     │                                                         │
│     ▼                                                         │
│  Widgets ────► panels (TopicsPanel, PlotPanel, ...)           │
│     │                                                         │
│     ▼                                                         │
│  RosBackend (thread-safe facade)                              │
│     │                                                         │
│     ▼                                                         │
│  rclpy MultiThreadedExecutor (background thread)              │
│     │                                                         │
│     ▼                                                         │
│  DDS / wire                                                   │
└───────────────────────────────────────────────────────────────┘
```

## Why the two-thread split

Textual's event loop is single-threaded asyncio. Spinning rclpy from the
same loop blocks the UI on every callback. `RosBackend` therefore owns a
`MultiThreadedExecutor` running on a daemon thread; subscriber callbacks
never touch widgets directly. Instead they:

1. Update the `Subscription` record (rate / bandwidth / last_msg)
2. Notify any registered Python callbacks under a lock

The Textual side polls these records on cheap timers (`set_interval`) and
re-renders.

## ROS layer

The `rosight.ros` package is intentionally importable without `rclpy`:

| Module | Purpose |
|--------|---------|
| `qos.py` | Plain-data `QoSSpec` + `negotiate()` to derive a subscriber QoS that matches every publisher. |
| `stats.py` | `RateMonitor` and `BandwidthMonitor` — sliding-window accumulators with thread-safe `tick`/`sample`. |
| `introspection.py` | `iter_fields(msg)` walks any ROS message (or duck-typed dict) and yields `FieldEntry(path, value, type, is_numeric)`. |
| `backend.py` | `RosBackend` — owns the rclpy node and executor; the only place rclpy is imported. |

Because the heavy imports are deferred to `RosBackend.start()`, the
package can be unit-tested on cloud CI runners without ROS 2 installed.

## Utilities

- `utils/ringbuffer.py` — `RingBuffer` (capacity-bounded) and
  `TimedRingBuffer` (window-bounded) used by stats and plot panel.
  Both lock-protected.
- `utils/path.py` — parses dotted/bracketed field paths and resolves them
  against any object (message, dict, list).
- `utils/formatting.py` — display helpers: `format_bytes`, `format_rate`,
  `format_value`, etc.

## Widgets

Each panel is a self-contained Textual `Vertical` with its own
`compose()`, `BINDINGS`, and CSS in `DEFAULT_CSS`. Cross-panel
communication goes through `RosightApp` (e.g. the message tree posts a
`FieldSelected` event that `TopicsPanel` forwards to
`app.add_plot_series`).

A few widgets are reusable:

- `MessageTree` renders any ROS message as a navigable tree and exposes
  `FieldSelected`.
- `PlotView` wraps `plotext` and turns a dict of `PlotSeries` into a
  rendered chart on a 15 Hz tick.

## Configuration

`config.py` defines a strict dataclass schema, loaded from TOML. Unknown
keys are dropped silently to preserve forward compatibility. The CLI can
override `domain_id` per run.

## Lifecycle

```
RosightApp.__init__
  └── on_mount
       ├── ros.start()        → executor thread starts
       └── set_interval(...)  → status bar tickers
RosightApp.on_unmount
  └── ros.stop()              → shuts down node, joins thread
```

If `ros.start()` raises `RosUnavailable`, the app stays up in degraded
mode and shows a notification — useful for offline UI work.

## Testing strategy

- **Pure-python tests** cover utilities, QoS logic, stats, introspection,
  config, and parsers. They run without rclpy.
- **Mocked-backend tests** verify the ROS facade without a real node.
- **Headless smoke tests** boot the Textual app via `App.run_test`
  (Textual's pilot harness) and exercise key bindings.
- **ROS integration job** (CI) runs the suite inside official `ros:humble`
  / `ros:jazzy` containers with a sourced workspace.

## Extending Rosight

To add a new panel:

1. Create `src/rosight/widgets/foo_panel.py` that subclasses `Vertical`
   (or another Textual container).
2. Register it in `RosightApp.compose` inside the `TabbedContent` block
   and add a number-key binding.
3. If the panel needs ROS data, prefer adding methods to `RosBackend`
   over reaching into rclpy from the widget.
4. Add a test under `tests/`.

See [development.md](development.md) for the full dev loop.
