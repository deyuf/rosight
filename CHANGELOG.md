# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

> **Renamed** from `lazyrosplus`. Pip distribution name, CLI command,
> Python import package and config directory are all now `rosight`.

### Added

- Textual-based TUI with nine tabs: Messages, Nodes, Services, Actions,
  Params, Plot, TF, Bags, Interfaces.
- `RosBackend` — thread-safe rclpy facade with `MultiThreadedExecutor`
  on a daemon thread, dynamic subscription management, and runtime
  `set_domain_id(N)`.
- Auto-negotiated QoS for subscribers (derived from publisher endpoints).
- Live multi-series plotter (`plotext`) with sliding-window buffer,
  pause / scale / CSV export.
- Auto-discovered TF tree from `/tf` and `/tf_static`.
- `ros2 bag` record / play passthrough (`stdin=DEVNULL` + own session so
  keystrokes never race with the TUI).
- `:domain N` command-palette entry — reconnect rclpy on a new
  `ROS_DOMAIN_ID` without restarting.
- Persistent theme via `state.toml` next to the user config; survives
  restarts without rewriting hand-edited `config.toml`.
- TOML configuration with `platformdirs` default location.
- CLI entry point (`rosight`) with `--config`, `--domain-id`, `--no-ros`,
  `--log-file`, `--log-level`, and `--version`.
- 80+ unit + headless-pilot smoke tests; rclpy-only integration tests
  spin a real `ros2 topic pub` subprocess and run in the `ros:humble` /
  `ros:jazzy` CI containers.
- GitHub Actions: lint + tests on Python 3.10–3.12, build, ROS 2
  integration smoke on `ros:humble` and `ros:jazzy`, PyPI release
  pipeline, MkDocs site deploy, dependabot auto-merge.
- Documentation: install, usage, keybindings (incl. command palette and
  terminal copy quirks), configuration (incl. state.toml + runtime
  domain switch), plotting, architecture, development, FAQ.
