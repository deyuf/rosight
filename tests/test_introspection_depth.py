"""Tests for the depth-limit warning in ``iter_fields``.

The walker bails out at depth > 32 to dodge pathological cycles. Prior
to this change it returned silently — users with truncated trees had
no diagnostic. We now log a warning that ``test_logging_caplog`` can
verify.
"""

from __future__ import annotations

import logging

from rosight.ros.introspection import _MAX_DEPTH, iter_fields


def test_depth_under_limit_no_warning(caplog):
    """A normal nested struct (depth 3) walks silently."""
    msg = {"a": {"b": {"c": 1}}}
    with caplog.at_level(logging.WARNING, logger="rosight.ros.introspection"):
        list(iter_fields(msg))
    assert "depth limit" not in caplog.text


def test_depth_over_limit_logs_warning(caplog):
    """Build a chain longer than _MAX_DEPTH and assert the warning fires."""
    # Construct nested dicts depth ~ _MAX_DEPTH + 5.
    msg: dict = {"leaf": 1}
    for _ in range(_MAX_DEPTH + 5):
        msg = {"child": msg}
    with caplog.at_level(logging.WARNING, logger="rosight.ros.introspection"):
        list(iter_fields(msg))
    assert "depth limit" in caplog.text
    assert str(_MAX_DEPTH) in caplog.text


def test_self_reference_does_not_recurse_forever(caplog):
    """A cycle must terminate via the depth guard rather than blowing the
    Python stack."""
    msg: dict = {}
    msg["self"] = msg
    with caplog.at_level(logging.WARNING, logger="rosight.ros.introspection"):
        entries = list(iter_fields(msg))
    # We didn't recurse infinitely…
    assert len(entries) < 1000
    # …and the warning surfaced.
    assert "depth limit" in caplog.text
