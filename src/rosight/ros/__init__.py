"""ROS 2 backend abstractions used by the TUI.

Importing this package does **not** import ``rclpy``. The backend lazily
imports rclpy inside :class:`RosBackend.start` so the rest of the package
(and the test suite) can run without a ROS 2 installation.
"""

from rosight.ros.backend import RosBackend, RosUnavailable, ros_available
from rosight.ros.stats import BandwidthMonitor, RateMonitor

__all__ = [
    "BandwidthMonitor",
    "RateMonitor",
    "RosBackend",
    "RosUnavailable",
    "ros_available",
]
