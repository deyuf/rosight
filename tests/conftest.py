"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

# Allow ``import lazyros`` even when the package is installed in editable
# mode under a different prefix than the test run env.
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


import pytest


@pytest.fixture
def tiny_message():
    """A duck-typed ROS message for testing introspection without rclpy."""

    class Vec3:
        __slots__ = ("x", "y", "z")

        def __init__(self, x=0.0, y=0.0, z=0.0):
            self.x, self.y, self.z = x, y, z

        @staticmethod
        def get_fields_and_field_types():
            return {"x": "float64", "y": "float64", "z": "float64"}

    class Twist:
        __slots__ = ("angular", "linear")

        def __init__(self):
            self.linear = Vec3(1.0, 2.0, 3.0)
            self.angular = Vec3(0.1, 0.2, 0.3)

        @staticmethod
        def get_fields_and_field_types():
            return {
                "linear": "geometry_msgs/Vector3",
                "angular": "geometry_msgs/Vector3",
            }

    return Twist()
