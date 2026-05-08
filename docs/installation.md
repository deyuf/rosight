# Installation

## Prerequisites

- Linux (Ubuntu 22.04 / 24.04 recommended)
- Python 3.10+
- A ROS 2 distribution (Humble, Iron, Jazzy or Rolling) — optional but
  required for any networked features

`lazyros` is a pure-Python package; it does not need to be in a colcon
workspace. It links to your sourced ROS 2 environment at runtime.

## From PyPI (recommended)

```bash
pip install lazyros
```

Then, in any terminal where you want to use it:

```bash
source /opt/ros/<distro>/setup.bash
lazyros
```

If you maintain multiple distros, source the one whose `rclpy` should drive
discovery before launching `lazyros`.

## Distro-specific notes

### Humble (Ubuntu 22.04)

```bash
sudo apt install python3-pip python3-venv
python3 -m venv ~/.venvs/lazyros
source ~/.venvs/lazyros/bin/activate
pip install lazyros
source /opt/ros/humble/setup.bash
# ROS-bundled rclpy must remain visible — venvs created with --system-site-packages help:
deactivate
python3 -m venv --system-site-packages ~/.venvs/lazyros
source ~/.venvs/lazyros/bin/activate
pip install lazyros
```

### Jazzy / Rolling

Same as Humble but use the matching distro setup script.

### Inside a colcon workspace

You can install it as a regular Python dep without making it a ROS package:

```bash
cd ~/ros2_ws
pip install lazyros --break-system-packages   # if your distro restricts pip
```

Or vendor it into a venv with system site packages and source it before
running.

## From source

```bash
git clone https://github.com/deyuf/lazyros
cd lazyros
pip install -e ".[dev]"
pytest
```

## Without ROS 2 (UI development)

```bash
pip install lazyros
lazyros --no-ros
```

Useful for working on widgets, themes, or integrations without sourcing a
distribution.

## Verify

```bash
lazyros --version    # prints "lazyros <version>"
lazyros --help       # shows CLI flags
```
