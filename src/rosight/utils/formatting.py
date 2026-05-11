"""Formatting helpers for human-readable display."""

from __future__ import annotations

import math
from typing import Any

_BYTE_UNITS = ["B", "KB", "MB", "GB", "TB"]
_TIME_UNITS = [("d", 86400.0), ("h", 3600.0), ("m", 60.0), ("s", 1.0)]


def format_bytes(n: float) -> str:
    """Format a byte count in a compact human-readable form."""
    if n < 0:
        return "?"
    v = float(n)
    for unit in _BYTE_UNITS:
        if v < 1024.0 or unit == _BYTE_UNITS[-1]:
            return f"{v:6.1f} {unit}"
        v /= 1024.0
    return f"{v:.1f} {_BYTE_UNITS[-1]}"


def format_rate(hz: float) -> str:
    """Format a frequency in Hz."""
    if hz <= 0 or math.isnan(hz):
        return "  --  "
    if hz >= 1000:
        return f"{hz / 1000:5.1f} kHz"
    if hz >= 1:
        return f"{hz:6.1f} Hz"
    return f"{hz * 1000:5.1f}mHz"


def format_duration(seconds: float) -> str:
    """Format a duration in a compact form like ``1h2m`` or ``3.4s``."""
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    parts: list[str] = []
    remaining = seconds
    for label, scale in _TIME_UNITS:
        v = int(remaining // scale)
        if v > 0 or (label == "s" and not parts):
            if label == "s":
                parts.append(f"{remaining:.1f}{label}" if not parts else f"{v}{label}")
            else:
                parts.append(f"{v}{label}")
            remaining -= v * scale
    return "".join(parts[:2])


def truncate(text: str, max_len: int, suffix: str = "…") -> str:
    """Truncate ``text`` to at most ``max_len`` chars."""
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= len(suffix):
        return suffix[:max_len]
    return text[: max_len - len(suffix)] + suffix


def short_type(type_name: str) -> str:
    """Shorten a fully-qualified ROS type like ``geometry_msgs/msg/Twist``.

    Returns ``Twist`` for plain display, but keeps the package namespace
    on collisions (handled by callers).
    """
    return type_name.rsplit("/", 1)[-1]


def format_value(value: Any, max_len: int = 60) -> str:
    """Compactly format a Python value for inline display."""
    if value is None:
        return "—"
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if abs(value) >= 1e6 or (value != 0 and abs(value) < 1e-3):
            return f"{value:.3e}"
        return f"{value:.4g}"
    if isinstance(value, bytes):
        return f"<{len(value)} bytes>"
    if isinstance(value, (list, tuple)):
        if len(value) > 6:
            return f"[{len(value)} items]"
        return truncate(repr(list(value)), max_len)
    return truncate(str(value), max_len)
