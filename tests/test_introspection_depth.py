"""Tests for the depth-limit warning in ``iter_fields``.

The walker bails out at depth > 32 to dodge pathological cycles. Prior
to this change it returned silently — users with truncated trees had
no diagnostic. We now log a warning at the rosight introspection logger.

Implementation note: CI's rosight venv installs handlers/filters that
prevent records from reaching ``caplog``'s root handler — records show
up on stderr but ``caplog.records`` stays empty. We sidestep the issue
by attaching our own ``ListHandler`` directly to the target logger,
which guarantees capture regardless of propagation state.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager

from rosight.ros.introspection import _MAX_DEPTH, iter_fields


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture(logger_name: str):
    """Attach a list-collecting handler directly to ``logger_name``.

    Works even when the logger has ``propagate=False`` or when external
    handlers swallow records before pytest's caplog sees them.
    """
    h = _ListHandler()
    lg = logging.getLogger(logger_name)
    prev_level = lg.level
    lg.addHandler(h)
    lg.setLevel(logging.DEBUG)
    try:
        yield h
    finally:
        lg.removeHandler(h)
        lg.setLevel(prev_level)


def _messages(h: _ListHandler, needle: str) -> list[str]:
    return [r.getMessage() for r in h.records if needle in r.getMessage()]


def test_depth_under_limit_no_warning():
    """A normal nested struct (depth 3) walks silently."""
    with _capture("rosight.ros.introspection") as h:
        list(iter_fields({"a": {"b": {"c": 1}}}))
    assert _messages(h, "depth limit") == []


def test_depth_over_limit_logs_warning():
    """Build a chain longer than _MAX_DEPTH and assert the warning fires."""
    msg: dict = {"leaf": 1}
    for _ in range(_MAX_DEPTH + 5):
        msg = {"child": msg}
    with _capture("rosight.ros.introspection") as h:
        list(iter_fields(msg))
    matched = _messages(h, "depth limit")
    assert matched, f"no 'depth limit' warning; records: {h.records!r}"
    assert any(str(_MAX_DEPTH) in m for m in matched)


def test_self_reference_does_not_recurse_forever():
    """A cycle must terminate via the depth guard rather than blowing the
    Python stack."""
    msg: dict = {}
    msg["self"] = msg
    with _capture("rosight.ros.introspection") as h:
        entries = list(iter_fields(msg))
    assert len(entries) < 1000
    assert _messages(h, "depth limit"), f"no warning for cycle; records: {h.records!r}"
