from __future__ import annotations

from lazyrosplus.utils.formatting import (
    format_bytes,
    format_duration,
    format_rate,
    format_value,
    short_type,
    truncate,
)


def test_format_bytes_units():
    assert "B" in format_bytes(0)
    assert "KB" in format_bytes(2048)
    assert "MB" in format_bytes(2 * 1024 * 1024)
    assert "GB" in format_bytes(2 * 1024**3)


def test_format_rate_special_values():
    assert "--" in format_rate(0)
    assert "--" in format_rate(float("nan"))
    assert "Hz" in format_rate(15.0)
    assert "kHz" in format_rate(1500.0)
    assert "mHz" in format_rate(0.5)


def test_format_duration():
    assert format_duration(0.123).endswith("ms")
    assert "s" in format_duration(2.0)
    assert "m" in format_duration(75)


def test_truncate():
    assert truncate("hello", 10) == "hello"
    assert truncate("hello world", 7).endswith("…")
    assert truncate("abc", 0) == ""


def test_short_type():
    assert short_type("geometry_msgs/msg/Twist") == "Twist"
    assert short_type("Twist") == "Twist"


def test_format_value_variants():
    assert format_value(None) == "—"
    assert "NaN" in format_value(float("nan"))
    assert format_value(0.5) == "0.5"
    assert "bytes" in format_value(b"\x00\x01\x02")
    assert format_value([1, 2, 3]) == "[1, 2, 3]"
    assert "items" in format_value(list(range(10)))
    assert "e" in format_value(1e9)
