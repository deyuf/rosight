# Installation

## Prerequisites

- Linux (Ubuntu 22.04 / 24.04 recommended)
- Python 3.10+
- A ROS 2 distribution (Humble, Iron, Jazzy or Rolling) — optional but
  required for any networked features

`lazyrosplus` is a pure-Python package; it does not need to be in a colcon
workspace. It links to your sourced ROS 2 environment at runtime.

> **Note:** LazyrosPlus is not yet published on PyPI. Install from source as
> shown below.

## From source (recommended)

```bash
git clone https://github.com/deyuf/lazyrosplus
cd lazyrosplus
pip install -e .
```

Then, in any terminal where you want to use it:

```bash
source /opt/ros/<distro>/setup.bash
lazyrosplus
```

If you maintain multiple distros, source the one whose `rclpy` should drive
discovery before launching `lazyrosplus`.

For development extras (tests, linters), use `pip install -e ".[dev]"`.

## Distro-specific notes

### Humble (Ubuntu 22.04)

```bash
sudo apt install python3-pip python3-venv git
git clone https://github.com/deyuf/lazyrosplus
# ROS-bundled rclpy must remain visible — venvs created with
# --system-site-packages let pip install LazyrosPlus into an isolated
# site-packages while keeping rclpy importable.
python3 -m venv --system-site-packages ~/.venvs/lazyrosplus
source ~/.venvs/lazyrosplus/bin/activate
pip install -e ./lazyrosplus
source /opt/ros/humble/setup.bash
```

### Jazzy / Rolling

Same as Humble but use the matching distro setup script.

### Inside a colcon workspace

You can install it as a regular Python dep without making it a ROS package:

```bash
cd ~/ros2_ws
pip install -e /path/to/lazyrosplus --break-system-packages   # if your distro restricts pip
```

Or vendor it into a venv with system site packages and source it before
running.

## Without ROS 2 (UI development)

```bash
pip install -e .
lazyrosplus --no-ros
```

Useful for working on widgets, themes, or integrations without sourcing a
distribution.

## Verify

```bash
lazyrosplus --version    # prints "lazyrosplus <version>"
lazyrosplus --help       # shows CLI flags
```
