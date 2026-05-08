# Changelog

All notable changes to this project are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - Unreleased

### Added

- Initial public release.
- Textual-based TUI with nine panels: Topics, Nodes, Services, Actions,
  Parameters, Plot, TF, Bags, Interfaces.
- `RosBackend` — thread-safe rclpy facade with multi-threaded executor
  and dynamic subscription management.
- Auto-negotiating QoS for subscribers based on publisher endpoints.
- Live multi-series plotter with sliding-window buffer, pause / scale /
  CSV export.
- Auto-discovered TF tree from `/tf` and `/tf_static`.
- `ros2 bag` record / play passthrough.
- TOML configuration with platformdirs default location.
- CLI entry point (`lazyrosplus`) with `--domain-id`, `--no-ros`, log file
  routing, and `--version`.
- Comprehensive unit, integration, and headless smoke test suite.
- GitHub Actions: lint + tests on Python 3.10–3.12, build, ROS 2
  integration on `ros:humble` and `ros:jazzy`, PyPI release pipeline,
  MkDocs site deploy.
- Documentation set: install, usage, keybindings, configuration, plotting,
  architecture, development, FAQ.
