# LazyrosPlus — design notes

This document captures the architectural decisions behind LazyrosPlus. It
complements [`docs/architecture.md`](docs/architecture.md) which is the
contributor-facing reference.

## Goals

1. **Keyboard-only operation** — discoverable like lazygit, no mouse
   required, works over SSH/tmux.
2. **Visualise the live ROS 2 graph** — every `ros2 topic|node|service|
   action|param|bag` subcommand has a panel equivalent.
3. **Real plotting** — terminal replacement for plotjuggler-style scoping
   of any numeric message field.
4. **Stable in degraded environments** — runs without ROS 2 installed
   (UI work) and tolerates flaky discovery.

## Non-goals

- 3-D visualisation (rviz territory).
- Bag editing/repackaging.
- Replacing the colcon build flow.

## Stack choice

Python + rclpy + Textual + plotext.

### Why Python

- `rclpy` is a first-class ROS 2 client.
- `rosidl_runtime_py` makes dynamic message-type lookup trivial.
- Textual is the most ergonomic modern TUI framework.

Considered alternatives:

- **Rust + ratatui + r2r/rclrs** — best performance, but the Rust ROS 2
  bindings are immature, dynamic type introspection is harder, and the
  development cost is higher.
- **C++ + FTXUI** — fastest path but slowest to ship.
- **Go + bubbletea** — lazygit's own stack, but the ROS 2 Go bindings are
  fringe.

If/when the Python plotting hot path becomes a bottleneck, a Rust sidecar
that streams pre-aggregated points over a Unix socket is the planned
escape hatch.

## Threading model

- Textual runs an asyncio event loop on the main thread.
- `RosBackend` owns a `rclpy.MultiThreadedExecutor` on a daemon thread.
- Subscriber callbacks fire on the executor and only mutate
  `Subscription` records, never widgets.
- Widgets pull from the records on their own `set_interval` timers.

This keeps the UI responsive even when topics fire at thousands of Hz.

## Data flow for a plot

```
publisher --DDS--> rclpy executor (bg thread)
                       │
                       ▼
                Subscription.last_msg
                       │
        PlotPanel timer (15 Hz)
                       │
        get_value(last_msg, field_path)
                       │
                       ▼
              TimedRingBuffer  (lock-protected)
                       │
                       ▼
              PlotView render (15 Hz)
```

The path between executor and UI is two atomic-ish writes (`last_msg`,
`last_msg_ts`) — no queues, no asyncio cross-thread shenanigans.

## QoS strategy

ROS 2's QoS matrix is the single biggest reason naive `ros2 topic echo`
fails on sensor topics. LazyrosPlus calls
`get_publishers_info_by_topic(topic)` and then derives a subscriber
profile that matches every publisher:

- Reliability: `BEST_EFFORT` if any publisher is `BEST_EFFORT`, else
  `RELIABLE`.
- Durability: `TRANSIENT_LOCAL` only when all publishers are; otherwise
  `VOLATILE`.
- History: always `KEEP_LAST` with a configurable depth.

This logic lives in `lazyrosplus.ros.qos.negotiate` and is unit-tested without
rclpy.

## Configuration philosophy

- TOML at a platform-appropriate path (`platformdirs.user_config_dir`).
- Strict dataclass schema, but unknown keys are ignored on load — old
  configs keep working as new fields land.
- All keys optional; the codebase always has working defaults.

## Testing matrix

| Layer | Test type | rclpy needed? |
|-------|-----------|---------------|
| Utilities | pure-python | no |
| QoS / stats / introspection | pure-python | no |
| Backend | mocked rclpy node | no |
| Widgets | headless smoke via Textual pilot | no |
| Live ROS | container job with `ros:humble` / `ros:jazzy` | yes |

## Forward-looking ideas

- Auto-form publisher / service caller using the message schema.
- Lifecycle node state machine view.
- Action goal/feedback monitor with state transitions.
- Configurable keybindings.
- Themes (`lazyrosplus-light`, `lazyrosplus-solarized`).
- Plugin hooks (`entry_points`) for custom panels.

These will land incrementally and won't break the public dataclass
schema.
