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


def fit_last_column_when_ready(table: Any) -> None:
    """Call ``fit_last_column`` after the next layout pass.

    Use from ``on_mount`` (where ``table.size`` is still zero) and
    ``on_resize``: by the time Textual finishes the current refresh cycle,
    the table has a real region and ``fit_last_column`` can compute the
    right widths.
    """
    try:
        table.call_after_refresh(fit_last_column, table)
    except Exception:
        # If the deferred call mechanism isn't available, fall back to a
        # direct call — it may no-op on the first attempt but the next
        # tick will get it right.
        fit_last_column(table)


def fit_last_column(table: Any) -> None:
    """Stretch the last column so the cursor highlight reaches the right edge.

    Textual's ``DataTable`` auto-sizes every column to its content. When the
    container is wider than the sum of those auto widths, the table's virtual
    width is narrower than its region — and the cursor row background only
    paints across the virtual width, leaving a misaligned gap on the right.
    Pinning the last column to ``remaining_width`` makes the row highlight
    span the full visible area.
    """
    try:
        cols = list(table.columns.values())
        if not cols:
            return
        width = table.size.width
        if width <= 0:
            return
        cell_pad = getattr(table, "cell_padding", 1)
        # Force DataTable to remeasure cell content widths so the
        # ``content_width`` we read below reflects the rows we just added,
        # not whatever was cached from the previous refresh.
        try:
            table._update_dimensions(list(table.rows))
        except Exception:
            pass
        # Sum auto-sized widths of every column except the last.
        other = 0
        for c in cols[:-1]:
            c.auto_width = True
            content = getattr(c, "content_width", 0) or 0
            other += content + 2 * cell_pad
        last = cols[-1]
        last_content = getattr(last, "content_width", 0) or 0
        # Reserve some slack for an eventual vertical scrollbar; never shrink
        # the last column below its own header text.
        target = max(last_content, width - other - 2 * cell_pad - 1)
        if last.width == target and not last.auto_width:
            return  # already correct, avoid forcing another layout pass
        last.auto_width = False
        last.width = target
        # `width`/`auto_width` are normal dataclass fields on Column, but
        # DataTable only recomputes `virtual_size` when it processes
        # ``_new_rows``. Mark every row dirty so the next idle pass picks up
        # the new column widths.
        try:
            table._new_rows.update(table.rows)
            table._require_update_dimensions = True
        except Exception:
            pass
        table.refresh(layout=True)
    except Exception:
        # Width tweaks are cosmetic — never crash the panel over them.
        pass
