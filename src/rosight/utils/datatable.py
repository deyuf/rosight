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
        if getattr(table, "_rosight_fit_cache", None) == cache_key:
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
            table._rosight_fit_cache = cache_key
            return
        last.auto_width = False
        last.width = target
        try:
            table._new_rows.update(table.rows)
            table._require_update_dimensions = True
        except Exception:
            pass
        table.refresh(layout=True)
        table._rosight_fit_cache = cache_key
    except Exception:
        # Width tweaks are cosmetic — never crash the panel over them.
        pass


def invalidate_fit_cache(table: Any) -> None:
    """Force ``fit_last_column`` to recompute on its next call.

    Use after the panel is resized — region width changes but column count
    doesn't, so we have to bust the cache explicitly.
    """
    try:
        table._rosight_fit_cache = None
    except Exception:
        pass


def sync_table(table: Any, rows: list[tuple[str, tuple[Any, ...]]]) -> bool:
    """Make ``table`` show ``rows`` (``(key, cells)`` pairs) with minimal work.

    * Same keys in the same order (the common case on a refresh tick):
      only cells whose value changed are rewritten via ``update_cell``.
      Cursor, scroll position and selection are untouched, so nothing
      flickers or jumps.
    * Keys added/removed/reordered: the table is rebuilt once, then the
      cursor is put back on the previously highlighted key and the scroll
      offset restored.

    Returns True when the table was rebuilt or a cell changed width (the
    caller should re-run :func:`fit_last_column`), False otherwise.
    """
    cache: dict[str, tuple[Any, ...]] = getattr(table, "_rosight_cells", None) or {}
    new_keys = [k for k, _ in rows]
    try:
        old_keys = [str(r.key.value) for r in table.ordered_rows]
    except Exception:
        old_keys = []

    if new_keys == old_keys and len(cache) == len(new_keys):
        col_keys = list(table.columns.keys())
        widened = False
        for key, cells in rows:
            prev = cache.get(key)
            if prev == cells:
                continue
            for idx, value in enumerate(cells):
                if prev is not None and idx < len(prev) and prev[idx] == value:
                    continue
                old_w = _cell_width(prev[idx]) if prev is not None and idx < len(prev) else -1
                if _cell_width(value) != old_w:
                    widened = True
                table.update_cell(key, col_keys[idx], value, update_width=True)
            cache[key] = cells
        table._rosight_cells = cache
        return widened

    selected = current_row_key(table)
    scroll = getattr(table, "scroll_offset", None)
    table.clear()
    # clear() keeps each column's measured content width, so a column that
    # once held a long value (e.g. an empty-state placeholder) would never
    # shrink back. Re-measure from the new rows only.
    for column in table.columns.values():
        if getattr(column, "auto_width", True):
            label = getattr(column, "label", "")
            column.content_width = getattr(label, "cell_len", len(str(label)))
    cache = {}
    new_idx = -1
    for idx, (key, cells) in enumerate(rows):
        table.add_row(*cells, key=key)
        cache[key] = cells
        if key == selected:
            new_idx = idx
    table._rosight_cells = cache
    restore_cursor(table, selected, new_idx)
    if scroll is not None:
        try:
            table.scroll_to(x=scroll.x, y=scroll.y, animate=False)
        except Exception:
            pass
    return True


def _cell_width(value: Any) -> int:
    plain = getattr(value, "plain", None)
    return len(plain if isinstance(plain, str) else str(value))


def ellipsize(text: str, width: int) -> str:
    """Cut ``text`` to ``width`` cells, ending in "…" when shortened."""
    if width <= 0:
        return ""
    return text if len(text) <= width else text[: max(0, width - 1)] + "…"


def ellipsize_left(text: str, width: int) -> str:
    """Like :func:`ellipsize` but keeps the end (useful for paths)."""
    if width <= 0:
        return ""
    return text if len(text) <= width else "…" + text[-(width - 1) :]


def table_width(table: Any) -> int:
    """Usable content width of a DataTable (0 when not laid out yet)."""
    try:
        return int(table.scrollable_content_region.width or table.size.width)
    except Exception:
        return 0


def set_columns(table: Any, columns: tuple[str, ...]) -> bool:
    """Replace the table's columns if they differ; True when changed."""
    current = tuple(str(c.label) for c in table.columns.values())
    if current == columns:
        return False
    table.clear(columns=True)
    table.add_columns(*columns)
    table._rosight_cells = None
    table._rosight_fit_cache = None
    return True


def ellipsize_middle(text: str, width: int) -> str:
    """Shorten the middle of ``text`` to ``width`` cells ("pkg/…/Type")."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width < 5:
        return ellipsize(text, width)
    tail = (width - 1) // 2 + (width - 1) % 2
    head = width - 1 - tail
    return text[:head] + "…" + text[-tail:]
