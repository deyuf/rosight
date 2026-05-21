"""Tests for the depth-limit warning in ``iter_fields``.

The walker bails out at depth > 32 to dodge pathological cycles. Prior
to this change it returned silently — users with truncated trees had
no diagnostic. We now log a warning that ``test_logging_caplog`` can
verify.

Implementation note: we ``caplog.set_level(WARNING)`` on the *root*
logger (no ``logger=`` arg) and assert on ``caplog.records`` rather
than ``caplog.text``. Some CI environments install handlers/filters
on the named logger that prevent ``caplog``'s root handler from
seeing the record otherwise — even though it still reaches stderr.
"""

from __future__ import annotations

import logging

from rosight.ros.introspection import _MAX_DEPTH, iter_fields


def _warnings_mentioning(caplog, needle: str) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.levelno >= logging.WARNING and needle in r.getMessage()
    ]


def test_depth_under_limit_no_warning(caplog):
    """A normal nested struct (depth 3) walks silently."""
    caplog.set_level(logging.WARNING)
    msg = {"a": {"b": {"c": 1}}}
    list(iter_fields(msg))
    assert _warnings_mentioning(caplog, "depth limit") == []


def test_depth_over_limit_logs_warning(caplog):
    """Build a chain longer than _MAX_DEPTH and assert the warning fires."""
    caplog.set_level(logging.WARNING)
    msg: dict = {"leaf": 1}
    for _ in range(_MAX_DEPTH + 5):
        msg = {"child": msg}
    list(iter_fields(msg))
    matched = _warnings_mentioning(caplog, "depth limit")
    assert matched, f"no 'depth limit' warning in {caplog.records!r}"
    assert any(str(_MAX_DEPTH) in m for m in matched)


def test_self_reference_does_not_recurse_forever(caplog):
    """A cycle must terminate via the depth guard rather than blowing the
    Python stack."""
    caplog.set_level(logging.WARNING)
    msg: dict = {}
    msg["self"] = msg
    entries = list(iter_fields(msg))
    # We didn't recurse infinitely…
    assert len(entries) < 1000
    # …and the warning surfaced.
    assert _warnings_mentioning(caplog, "depth limit"), (
        f"no warning logged for cycle; records: {caplog.records!r}"
    )
