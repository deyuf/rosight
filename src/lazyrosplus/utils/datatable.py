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

    Hot path: called from every panel's ``_render_table``. We cache the
    ``(region_width, column_count)`` we last fitted for and short-circuit when
    nothing changed, so the per-tick cost on a 100-row table is a single int
    compare — not a full ``_update_dimensions(list(rows))`` pass plus a forced
    layout.
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
        # ``content_width`` we read below reflects the rows we just added.
        try:
            table._update_dimensions(list(table.rows))
        except Exception:
            pass

        # Fast path: same region + same column shape + same row population.
        # Cache key includes row_count so adding/removing rows always refits;
        # includes sum-of-non-last-content-width so a longer service name in
        # a refresh tick also refits.
        col_count = len(cols)
        sum_other_content = sum((getattr(c, "content_width", 0) or 0) for c in cols[:-1])
        cache_key = (width, col_count, table.row_count, sum_other_content)
        if getattr(table, "_lazyrosplus_fit_cache", None) == cache_key:
            return

        other = 0
        for c in cols[:-1]:
            c.auto_width = True
            content = getattr(c, "content_width", 0) or 0
            other += content + 2 * cell_pad
        last = cols[-1]
        last_content = getattr(last, "content_width", 0) or 0
        # Match the table region exactly. An earlier "-1" left a 1-cell strip
        # on the right of every row where the row background still painted
        # (panel bg / zebra stripe) but the cursor cell highlight didn't —
        # so the orange cursor bar looked shorter than the row's bg bar.
        # Panels already have `overflow: hidden` so we don't need to leave
        # room for a horizontal scrollbar.
        target = max(last_content, width - other - 2 * cell_pad)
        if last.width == target and not last.auto_width:
            table._lazyrosplus_fit_cache = cache_key
            return
        last.auto_width = False
        last.width = target
        try:
            table._new_rows.update(table.rows)
            table._require_update_dimensions = True
        except Exception:
            pass
        table.refresh(layout=True)
        table._lazyrosplus_fit_cache = cache_key
    except Exception:
        # Width tweaks are cosmetic — never crash the panel over them.
        pass


def invalidate_fit_cache(table: Any) -> None:
    """Force ``fit_last_column`` to recompute on its next call.

    Use after the panel is resized — region width changes but column count
    doesn't, so we have to bust the cache explicitly.
    """
    try:
        table._lazyrosplus_fit_cache = None
    except Exception:
        pass
