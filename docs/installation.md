# Installation

## Prerequisites

- Linux (Ubuntu 22.04 / 24.04 recommended)
- Python 3.10+
- A ROS 2 distribution (Humble, Iron, Jazzy or Rolling) — optional but
  required for any networked features

`rosight` is a pure-Python package; it does not need to be in a colcon
workspace. It links to your sourced ROS 2 environment at runtime.

> **Note:** Rosight is not yet published on PyPI. Install from source as
> shown below.

## From source (recommended)

```bash
git clone https://github.com/deyuf/rosight
cd rosight
pip install -e .
```

Then, in any terminal where you want to use it:

```bash
source /opt/ros/<distro>/setup.bash
rosight
```

If you maintain multiple distros, source the one whose `rclpy` should drive
discovery before launching `rosight`.

For development extras (tests, linters), use `pip install -e ".[dev]"`.

## Distro-specific notes

### Humble (Ubuntu 22.04)

```bash
sudo apt install python3-pip python3-venv git
git clone https://github.com/deyuf/rosight
# ROS-bundled rclpy must remain visible — venvs created with
# --system-site-packages let pip install Rosight into an isolated
# site-packages while keeping rclpy importable.
python3 -m venv --system-site-packages ~/.venvs/rosight
source ~/.venvs/rosight/bin/activate
pip install -e ./rosight
source /opt/ros/humble/setup.bash
```

### Jazzy / Rolling

Same as Humble but use the matching distro setup script.

### Inside a colcon workspace

You can install it as a regular Python dep without making it a ROS package:

```bash
cd ~/ros2_ws
pip install -e /path/to/rosight --break-system-packages   # if your distro restricts pip
```

Or vendor it into a venv with system site packages and source it before
running.

## Without ROS 2 (UI development)

```bash
pip install -e .
rosight --no-ros
```

Useful for working on widgets, themes, or integrations without sourcing a
distribution.

## Verify

```bash
rosight --version    # prints "rosight <version>"
rosight --help       # shows CLI flags
```
