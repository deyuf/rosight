# Architecture

This page is a tour of the codebase, in the order you'd encounter the
layers when tracing a single keystroke from the user to a ROS message.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Keyboard                                                            │
│     │                                                                │
│     ▼                                                                │
│  Textual main loop (asyncio) ── never calls rclpy synchronously      │
│     │   panels read O(1) snapshots on timers; slow calls → workers   │
│     ▼                                                                │
│  Widgets ────► panels (TopicsPanel, PlotPanel, GraphListPanel …)     │
│     │                                                                │
│     ▼                                                                │
│  RosBackend (thread-safe facade)                                     │
│     ├── GraphMonitor thread ── collects the graph once per period    │
│     ├── executor thread ────── SingleThreadedExecutor.spin()         │
│     │                          raw subscriptions: store bytes only   │
│     └── worker threads ─────── service calls, params, action goals,  │
│                                domain switch / reconnect             │
│     ▼                                                                │
│  DDS / wire                                                          │
└──────────────────────────────────────────────────────────────────────┘
```

## Threads and who does what

Textual's event loop is single-threaded asyncio; anything that blocks it
freezes the UI. Rosight keeps rclpy off that loop entirely:

| Thread | Work | Talks to the UI via |
|--------|------|---------------------|
| **Textual loop** | rendering, key handling, timers | — |
| **Executor** (`rosight-ros-executor`) | `SingleThreadedExecutor.spin()`; subscription callbacks | `Subscription` fields under a lock |
| **Graph monitor** (`rosight-graph-monitor`) | `list_topics/nodes/services/actions` once per `ui.discovery_period` | immutable `GraphSnapshot` |
| **Workers** (`asyncio.to_thread` / `run_worker`) | service calls, parameter get/set, action goals, `:domain`, `:reconnect`, publish | awaited results; `call_from_thread` for live action feedback |

### Raw subscriptions and lazy decoding

Subscriptions are created with `raw=True`. The executor callback
(`Subscription.ingest_raw`) only

1. ticks the `RateMonitor`,
2. adds `len(bytes)` to the `BandwidthMonitor` (exact size, no work),
3. stores the bytes and the receive time, and appends them to a bounded
   history ring (100 messages / 16 MB).

Nothing is deserialized there. When a widget wants the message it calls
`Subscription.snapshot()`, which runs `deserialize_message` **once per
received message** and caches the result; repeated reads are free and a
100 Hz topic shown at 4 Hz is decoded 4 times a second, not 100.

On rclpy builds without `raw` / `event_callbacks` support the backend falls
back step by step (raw + QoS events → raw → decoded + events → decoded); in
decoded mode the size estimate is throttled to once per second.
Incompatible-QoS events are recorded on the subscription and surfaced in
the Topics panel.

### Graph discovery

`GraphMonitor` (`ros/discovery.py`) collects the whole graph on its own
thread and publishes a frozen `GraphSnapshot` with a `generation` counter
that only increases when the content changes. The status bar and every
list panel read `ros.graph_snapshot()` in O(1) and skip re-rendering when
the generation is unchanged. `r` wakes the monitor for an immediate
collection. Generation 0 means "nothing discovered yet" and drives the
*discovering…* empty state.

## ROS layer

`rosight.ros` is importable without `rclpy`; heavy imports happen in
`RosBackend.start()`.

| Module | Purpose |
|--------|---------|
| `backend.py` | `RosBackend` (lifecycle, subscriptions, publish, services, parameters, action goals, health) and `Subscription` (raw ingest, lazy decode, history, QoS events). The only module that imports rclpy. |
| `discovery.py` | `GraphMonitor` thread and `GraphSnapshot`. |
| `qos.py` | Plain-data `QoSSpec` + `negotiate()` to derive a subscriber QoS that matches every publisher. |
| `stats.py` | `RateMonitor` / `BandwidthMonitor` — thread-safe sliding windows. |
| `introspection.py` | `iter_fields(msg)` walks any ROS message (or duck-typed object) and yields `FieldEntry(path, value, type, is_numeric, is_array_numeric)`. |
| `yaml_msg.py` | Message ↔ YAML for the publish / call / goal forms (`rosidl_runtime_py` when available). |

## Utilities

- `utils/datatable.py` — `sync_table()` updates a `DataTable` in place
  (only changed cells; rebuild only when rows are added/removed, keeping
  the cursor on the same key) and `fit_last_column()`.
- `utils/fuzzy.py` — subsequence, multi-term filter used by every panel.
- `utils/ringbuffer.py` — `RingBuffer` / `TimedRingBuffer` for plot data.
- `utils/path.py` — dotted/bracketed field paths, parsed once and cached.
- `utils/formatting.py` — `format_bytes`, `format_rate`, `sparkline`, …

## Widgets

Each panel is a self-contained Textual container with its own
`compose()`, `BINDINGS` and `DEFAULT_CSS`. Cross-panel actions go through
`RosightApp` (`add_plot_series`, `goto_topic`, `goto_service`,
`unsubscribe_topic`, `export_path`).

- `GraphListPanel` (`widgets/_base.py`) — Nodes, Services and Actions:
  filterable table over one kind of graph entity, empty states, generation
  skipping. Subclasses only describe columns and the detail pane.
- `MessageTree` — any message as a tree. Same structure → labels updated in
  place (changed values flash); new structure → rebuild that keeps
  expanded nodes and the cursor path. Search (`/`, `n`, `N`) and copy
  (`y`, `Y`).
- `PlotView` — wraps `plotext`; time-series and snapshot subplots on a
  15 Hz tick.
- `YamlFormScreen` — modal YAML editor with inline validation, shared by
  publish, service call, action goal and parameter set.
- `CommandPalette` + `CommandSuggester` — `:` commands with completion and
  history.

## Configuration and state

`config.py` defines a strict dataclass schema loaded from TOML; unknown
keys are dropped for forward compatibility. Runtime state (theme, last
tab, filters, plot series, command history) lives in a separate
`state.toml` so the hand-written config is never rewritten.

## Lifecycle

```
RosightApp.on_mount
  ├── ros.start()          → executor thread + graph monitor start
  ├── restore state.toml   → tab, filters, plot series (plot resubscribes
  │                          until its topics are discovered)
  └── set_interval(...)    → status ticker (also watches executor health)
q / :quit
  ├── confirm if a bag is recording / playing
  └── save state.toml
RosightApp.on_unmount
  ├── BagsPanel stops children (SIGINT → SIGTERM → SIGKILL, bounded)
  └── ros.stop()           → graph thread, executor.shutdown(timeout),
                             spin-thread join(timeout): never hangs
```

If `ros.start()` raises `RosUnavailable` the app stays up in degraded mode
with a notification. If the executor thread dies later, the status bar
turns red and `:reconnect` restarts the backend.

## Testing strategy

- **Pure-python tests** — utilities, QoS, stats, introspection, YAML
  conversion, config / state files.
- **Fake-node backend tests** — subscription fallback ladder, raw ingest
  and decode counts, QoS events, bounded shutdown, service timeouts,
  action goals (fake `rclpy.action`), real child processes for bag stop.
- **Headless UI tests** — boot the app with `App.run_test` and drive keys:
  panels, forms, navigation, palette completion, state restore.
- **Help sync** — `test_help_in_sync` fails if a binding or palette command
  is added without being documented in the help overlay.
- **ROS integration job** (CI) — the whole suite plus a headless launch
  inside `ros:humble` and `ros:jazzy` containers with real rclpy.

## Extending Rosight

To add a new panel:

1. Create `src/rosight/widgets/foo_panel.py`. If it lists a kind of graph
   entity, subclass `GraphListPanel`; otherwise a Textual `Vertical`.
2. Register it in `RosightApp.compose` inside the `TabbedContent` block
   and add a number-key binding.
3. Keep rclpy out of the widget: add a `RosBackend` method, and run
   anything that can block in a worker.
4. Document its keys in `widgets/help_screen.py` (the help-sync test will
   remind you) and add tests under `tests/`.

See [development.md](development.md) for the full dev loop.
