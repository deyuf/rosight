"""Field-path parsing and traversal for ROS messages.

A *field path* is a dotted/bracketed string identifying a value inside a
nested message, e.g. ``twist.linear.x`` or ``poses[3].position.y``.
The same syntax is used in the plot panel and the auto-generated forms.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_TOKEN = re.compile(
    r"""
    \. |              # dot separator
    \[\s*(-?\d+)\s*\] |  # array index
    ([A-Za-z_][A-Za-z0-9_]*)  # identifier
""",
    re.VERBOSE,
)


@dataclass(frozen=True, slots=True)
class PathStep:
    """A single step in a field path."""

    name: str | None = None  # attribute name
    index: int | None = None  # array index

    def __str__(self) -> str:
        if self.index is not None:
            return f"[{self.index}]"
        return self.name or ""


def parse_path(path: str) -> list[PathStep]:
    """Parse a field path string into a list of :class:`PathStep`.

    >>> parse_path("twist.linear.x")
    [PathStep(name='twist', ...), PathStep(name='linear', ...), PathStep(name='x', ...)]
    >>> parse_path("poses[2].position.x")[1]
    PathStep(name=None, index=2)
    """
    if not path:
        return []
    # Strip leading slash (some users mirror topic-path style)
    path = path.lstrip("/")
    steps: list[PathStep] = []
    pos = 0
    while pos < len(path):
        m = _TOKEN.match(path, pos)
        if not m:
            raise ValueError(f"invalid field path near {path[pos:]!r}")
        if m.group(1) is not None:
            steps.append(PathStep(index=int(m.group(1))))
        elif m.group(2) is not None:
            steps.append(PathStep(name=m.group(2)))
        # else: bare dot — skipped
        pos = m.end()
    return steps


def format_path(steps: list[PathStep]) -> str:
    """Render a list of steps as a canonical path string."""
    out: list[str] = []
    for s in steps:
        if s.index is not None:
            out.append(f"[{s.index}]")
        else:
            if out:
                out.append(".")
            out.append(s.name or "")
    return "".join(out)


def get_value(obj: Any, path: str | list[PathStep]) -> Any:
    """Resolve a field path against ``obj`` (a ROS message, dict, or list).

    Raises :class:`KeyError` if any step cannot be resolved. Returns ``None``
    if a step encounters a ``None`` value mid-traversal.
    """
    steps = parse_path(path) if isinstance(path, str) else list(path)
    cur: Any = obj
    for s in steps:
        if cur is None:
            return None
        if s.index is not None:
            try:
                cur = cur[s.index]
            except (IndexError, TypeError) as e:
                raise KeyError(f"index {s.index} not in {type(cur).__name__}") from e
        else:
            assert s.name is not None
            if isinstance(cur, dict):
                if s.name not in cur:
                    raise KeyError(s.name)
                cur = cur[s.name]
            else:
                if not hasattr(cur, s.name):
                    raise KeyError(s.name)
                cur = getattr(cur, s.name)
    return cur


def is_numeric(value: Any) -> bool:
    """Return True if ``value`` is plottable on a Y-axis."""
    if isinstance(value, bool):
        return True  # plot as 0/1
    return isinstance(value, (int, float))
