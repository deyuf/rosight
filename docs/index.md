# lazyros

A lazygit-style terminal UI for ROS 2.

`lazyros` gives you a fast, keyboard-driven view of every running ROS 2
graph: topics, nodes, services, actions, parameters, TF, and bags. It also
embeds a live multi-series plotter so you can scope numeric fields without
firing up `rqt_plot` or `plotjuggler`.

## Why lazyros

- **No GUI required.** Runs over SSH, in a tmux pane, or on a robot console.
- **Discovery without typing.** Tab through panels, fuzzy-filter, drill into
  endpoints — never write a long `ros2 topic info` invocation again.
- **Live plotting.** Pick any numeric leaf in any message and start scoping it
  in one keystroke.
- **Works without ROS 2.** The package imports cleanly without `rclpy` so
  you can run unit tests and CI on cloud hosts; live ROS panels light up the
  moment a workspace is sourced.

## Next steps

- [Install](installation.md) on your distro
- Read the [usage guide](usage.md)
- Learn the [keybindings](keybindings.md)
- Tune the [configuration](configuration.md)
- Skim the [architecture](architecture.md) before contributing
