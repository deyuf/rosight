"""Shared building blocks for panels that list ROS graph entities.

Nodes, Services and Actions used to carry near-identical copies of the same
~60 lines: poll the backend on a timer, clear + refill the table, restore
cursor and scroll, fit the last column, filter, dedupe row-highlight events.
:class:`GraphListPanel` holds that once; subclasses describe their columns
and detail view.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, ClassVar

from rich.text import Text
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input

from rosight.utils.datatable import fit_last_column, fit_last_column_when_ready, sync_table
from rosight.utils.fuzzy import matches

if TYPE_CHECKING:
    from rosight.app import RosightApp
    from rosight.ros.backend import RosBackend

log = logging.getLogger(__name__)

PLACEHOLDER_KEY = "__placeholder__"


def fetch_graph_items(ros: Any, field: str, list_method: str) -> tuple[list[Any], int | None]:
    """Return ``(items, generation)`` for one kind of graph entity.

    Uses the backend's O(1) :meth:`graph_snapshot` when available; falls
    back to the synchronous ``list_*`` method for duck-typed backends (tests
    swap in small stubs). ``generation`` is ``None`` on the fallback path,
    meaning "unknown, always re-render".
    """
    snap_fn = getattr(ros, "graph_snapshot", None)
    if callable(snap_fn):
        snap = snap_fn()
        return list(getattr(snap, field)), snap.generation
    return list(getattr(ros, list_method)()), None


def empty_state_text(ros: Any, generation: int | None, filter_text: str, noun: str) -> str:
    """Human-readable reason a table is empty."""
    if ros is None or not getattr(ros, "started", False):
        return "ROS backend not running"
    if generation == 0:
        return "discovering…"
    if filter_text.strip():
        return f"no {noun} match {filter_text.strip()!r}"
    return f"no {noun} on this ROS domain"


def placeholder_row(text: str, columns: int) -> tuple[str, tuple[Any, ...]]:
    cells: tuple[Any, ...] = (Text(text, style="dim italic"),) + ("",) * (columns - 1)
    return PLACEHOLDER_KEY, cells


class GraphListPanel(Vertical):
    """A filterable table of one ROS graph entity type plus a detail pane.

    Subclasses set the class attributes and implement :meth:`_row_cells`,
    :meth:`_row_key`, :meth:`_match_fields` and :meth:`_on_selected`;
    ``compose`` stays in the subclass because each panel lays out its own
    detail widgets.
    """

    TABLE_ID: ClassVar[str]
    COLUMNS: ClassVar[tuple[str, ...]]
    GRAPH_FIELD: ClassVar[str]  # attribute on GraphSnapshot
    LIST_METHOD: ClassVar[str]  # fallback RosBackend method
    CACHE_ATTR: ClassVar[str]  # kept for back-compat (tests poke it)
    NOUN: ClassVar[str] = "items"
    REFRESH_SECONDS: ClassVar[float] = 1.0

    filter_text: reactive[str] = reactive("")
    selected: reactive[str | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        setattr(self, self.CACHE_ATTR, [])
        self._graph_gen: int | None = None

    # ----- subclass hooks ------------------------------------------------

    def _row_key(self, item: Any) -> str:
        return str(item.name)

    def _row_cells(self, item: Any) -> tuple[Any, ...]:  # pragma: no cover - abstract
        raise NotImplementedError

    def _match_fields(self, item: Any) -> tuple[str, ...]:
        return (str(item.name),)

    def _on_selected(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    # ----- plumbing --------------------------------------------------------

    @property
    def app_(self) -> RosightApp:
        return self.app  # type: ignore[return-value]

    @property
    def ros(self) -> RosBackend | None:
        return getattr(self.app, "ros", None)

    @property
    def items(self) -> list[Any]:
        return getattr(self, self.CACHE_ATTR)

    def _table(self) -> DataTable:
        return self.query_one(f"#{self.TABLE_ID}", DataTable)

    def on_mount(self) -> None:
        table = self._table()
        table.add_columns(*self.COLUMNS)
        fit_last_column_when_ready(table)
        self._refresh(force=True)
        if not self.items:
            self._render_table()
        self.set_interval(self.REFRESH_SECONDS, self._refresh)

    def on_resize(self) -> None:
        fit_last_column_when_ready(self._table())

    def on_show(self) -> None:
        # Fresh data immediately on tab switch.
        self._refresh(force=True)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value
            self._render_table()

    def action_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    def _refresh(self, force: bool = False) -> None:
        # Hidden tab: do nothing at all — not even an O(1) snapshot read.
        if self.region.width == 0:
            return
        ros = self.ros
        if ros is None or not ros.started:
            return
        try:
            items, gen = fetch_graph_items(ros, self.GRAPH_FIELD, self.LIST_METHOD)
        except Exception:
            log.exception("fetching %s failed", self.NOUN)
            return
        if gen is not None and gen == self._graph_gen and not force:
            return  # graph unchanged since last render
        self._graph_gen = gen
        setattr(self, self.CACHE_ATTR, items)
        self._render_table()

    def _render_table(self) -> None:
        table = self._table()
        rows = [
            (self._row_key(item), self._row_cells(item))
            for item in self.items
            if matches(self.filter_text, *self._match_fields(item))
        ]
        if not rows:
            text = empty_state_text(self.ros, self._graph_gen, self.filter_text, self.NOUN)
            rows = [placeholder_row(text, len(self.COLUMNS))]
        if sync_table(table, rows):
            fit_last_column(table)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != self.TABLE_ID or event.row_key is None:
            return
        key = str(event.row_key.value)
        # The refresh tick re-fires this event when restoring the cursor;
        # skip the (possibly expensive) detail update if nothing moved.
        if key in (PLACEHOLDER_KEY, self.selected):
            return
        self.selected = key
        self._on_selected()
