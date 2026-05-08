# LazyrosPlus

[![CI](https://github.com/deyuf/lazyrosplus/actions/workflows/ci.yml/badge.svg)](https://github.com/deyuf/lazyrosplus/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A **lazygit-inspired terminal UI for ROS 2**. Browse topics, nodes, services,
actions, parameters and TF — subscribe to messages, watch hz/bw stats, and
plot any numeric field over time, all from a single keyboard-driven interface.

```
┌─Topics──────────────────────────┬─/odom─────────────────────────────────────┐
│ /odom            nav…/Odometry  │ hz: 49.8 Hz   bw: 31.2 KB/s   jitter: 0.3 │
│ /scan            sen…/LaserScan │ ▾ pose                                    │
│ /tf              tf2…/TFMessage │   ▾ pose                                  │
│ /cmd_vel         geo…/Twist     │     ▸ position                            │
│ /joint_states    sen…/JointSt…  │     ▸ orientation                         │
│ ...                             │ ▾ twist                                   │
│                                 │   ▾ twist                                 │
│                                 │     linear  Vector3                       │
│                                 │       x  0.182  : float64        <-       │
│                                 │       y  0.0    : float64                 │
└─────────────────────────────────┴───────────────────────────────────────────┘
 ● ros DOMAIN_ID=0  topics=42  nodes=11  srv=63  act=4  subs=3
                                                       [?] help  [:] command
```

## Features

- **Topics** — list, echo, subscribe, hz / bandwidth / jitter, QoS endpoints
- **Nodes** — list, info (publishers / subscribers / services / clients)
- **Services** — list, type, call (auto-form planned)
- **Actions** — list, type, send_goal & monitor (planned)
- **Parameters** — per-node list, get / set, type-aware
- **Plot** — multi-series live plotting of any numeric field, sliding window,
  pause / scale / CSV export
- **TF** — auto-built frame tree from `/tf` and `/tf_static`
- **Bags** — record and play via `ros2 bag` subprocess
- **Interfaces** — browse `msg` / `srv` / `action` definitions
- **Auto QoS** — subscriber QoS is derived from publisher endpoints
- **Vim-style keys** + `:command` palette + `?` help overlay

## Install

LazyrosPlus is not yet published to PyPI; install from source:

```bash
git clone https://github.com/deyuf/lazyrosplus
cd lazyrosplus
pip install -e .
# or, in your ROS 2 workspace:
source /opt/ros/<distro>/setup.bash
pip install -e .
lazyrosplus
```

See [`docs/installation.md`](docs/installation.md) for distribution-specific
notes (Humble, Iron, Jazzy, Rolling).

## Quick start

```bash
# launch (uses ROS_DOMAIN_ID from env)
lazyrosplus

# pick a domain and write logs to a file
lazyrosplus --domain-id 5 --log-file /tmp/lazyrosplus.log

# ui-only, no ROS connection
lazyrosplus --no-ros
```

Press `?` at any time for the full keyboard reference, or `:` for the command
palette.

## Documentation

| Topic | File |
|-------|------|
| Installation per distro | [docs/installation.md](docs/installation.md) |
| Daily usage | [docs/usage.md](docs/usage.md) |
| Keybindings | [docs/keybindings.md](docs/keybindings.md) |
| Configuration | [docs/configuration.md](docs/configuration.md) |
| Plotting deep-dive | [docs/plotting.md](docs/plotting.md) |
| Architecture | [docs/architecture.md](docs/architecture.md) |
| Contributing | [docs/development.md](docs/development.md) |
| FAQ | [docs/faq.md](docs/faq.md) |

## Project layout

```
src/lazyrosplus/
├── app.py            # Textual App, panel registry, key bindings
├── cli.py            # argparse entry point
├── config.py         # TOML config loader
├── ros/
│   ├── backend.py    # central rclpy facade
│   ├── introspection.py  # dynamic message-type resolution
│   ├── qos.py        # plain-data QoS + auto-negotiation
│   └── stats.py      # hz / bw monitors
├── utils/
│   ├── ringbuffer.py # thread-safe bounded buffers
│   ├── path.py       # message field-path parser
│   └── formatting.py # human-readable display helpers
└── widgets/          # Topics / Nodes / Services / Actions / Params / Plot /
                     # TF / Bags / Interfaces panels + status bar / help / palette
```

## License

MIT. See [`LICENSE`](LICENSE).
