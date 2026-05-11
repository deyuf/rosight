"""DataTable helpers shared across panels."""

from __future__ import annotations

from typing import Any


def current_row_key(table: Any) -> str | None:
    """Return the row_key value under the cursor, or None."""
    try:
        row = table.cursor_row
        if row is None or row < 0 or row >= table.row_count:
            return None
        row_key, _ = table.coordinate_to_cell_key((row, 0))
        return None if row_key is None else str(row_key.value)
    except Exception:
        return None


def restore_cursor(table: Any, key: str | None, index: int) -> None:
    """Move the table cursor to ``index`` (which corresponds to ``key``).

    ``key`` is unused for now but accepted for documentation/safety so callers
    don't accidentally pass the wrong index.
    """
    if key is None or index < 0:
        return
    try:
        table.move_cursor(row=index, animate=False)
    except Exception:
        pass
