"""Plot panel: live multi-series plot of selected message fields."""

from __future__ import annotations

import csv
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Static

from rosight.utils.datatable import fit_last_column_when_ready
from rosight.utils.formatting import format_value
from rosight.utils.path import get_value, parse_path
from rosight.widgets.plot_view import PlotSeries, PlotView, SnapshotSeries

SeriesKind = Literal["scalar", "array"]
MAX_SNAPSHOT_LEN = 4096

if TYPE_CHECKING:
    from rosight.app import RosightApp
    from rosight.ros.backend import RosBackend

log = logging.getLogger(__name__)


class PlotPanel(Vertical):
    """Plotter with side legend listing every series."""

    BINDINGS = [
        Binding("space", "toggle_pause", "Pause"),
        Binding("plus,equals_sign", "wider", "Window+"),
        Binding("minus", "narrower", "Window-"),
        Binding("c", "clear", "Clear"),
        Binding("l", "toggle_legend", "Legend"),
        Binding("d", "delete_series", "Delete"),
        Binding("s", "save_csv", "Save CSV"),
    ]

    DEFAULT_CSS = """
    PlotPanel { layout: horizontal; overflow: hidden; }
    PlotPanel > #plot-area { width: 1fr; overflow: hidden; }
    PlotPanel > #side {
        width: 30%; min-width: 30;
        border-left: solid $primary 30%;
        overflow: hidden;
    }
    PlotPanel #side-header { background: $boost; padding: 0 1; }
    PlotPanel PlotView { height: 1fr; }
    PlotPanel #side-table { height: 1fr; }
    """

    def __init__(self) -> None:
        super().__init__()
        # mapping: series_label -> (topic, field_path, kind)
        self._sources: dict[str, tuple[str, str, SeriesKind]] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id="plot-area"):
            yield PlotView(id="plot")
        with Vertical(id="side"):
            yield Static("Series", id="side-header")
            yield DataTable(id="side-table", cursor_type="row")

    def on_mount(self) -> None:
        st = self.query_one("#side-table", DataTable)
        st.add_columns("Series", "Last")
        fit_last_column_when_ready(st)
        # Sample subscribed topics' last_msg at refresh_hz to push points.
        self.set_interval(1 / 15, self._sample)
        self.set_interval(1.0, self._refresh_table)

    def on_resize(self) -> None:
        fit_last_column_when_ready(self.query_one("#side-table", DataTable))

    @property
    def ros(self) -> RosBackend | None:
        return getattr(self.app, "ros", None)

    @property
    def app_(self) -> RosightApp:
        return self.app  # type: ignore[return-value]

    @property
    def plot(self) -> PlotView:
        return self.query_one("#plot", PlotView)

    # -------- adding series ---------------------------------------------

    def add_series(self, topic: str, field_path: str) -> str:
        label = f"{topic}/{field_path}"
        if label in self._sources:
            return label
        self._sources[label] = (topic, field_path, "scalar")
        self.plot.add_series(label)
        self._auto_subscribe(topic)
        return label

    def add_snapshot_series(self, topic: str, field_path: str) -> str:
        label = f"{topic}/{field_path}"
        if label in self._sources:
            return label
        self._sources[label] = (topic, field_path, "array")
        self.plot.add_snapshot_series(label)
        self._auto_subscribe(topic)
        return label

    def _auto_subscribe(self, topic: str) -> None:
        ros = self.ros
        if ros is not None and ros.started and ros.get_subscription(topic) is None:
            try:
                ros.subscribe(topic)
            except Exception:
                log.exception("auto-subscribe failed for %s", topic)

    def _sample(self) -> None:
        ros = self.ros
        if ros is None or not ros.started or not self._sources:
            return
        ts = time.monotonic()
        for label, (topic, field_path, kind) in self._sources.items():
            sub = ros.get_subscription(topic)
            if sub is None or sub.last_msg is None:
                continue
            try:
                steps = parse_path(field_path)
                value = get_value(sub.last_msg, steps)
            except Exception:
                continue
            if kind == "scalar":
                if isinstance(value, bool):
                    self.plot.push(label, 1.0 if value else 0.0, ts)
                elif isinstance(value, (int, float)):
                    self.plot.push(label, float(value), ts)
            elif kind == "array" and (
                isinstance(value, (list, tuple)) or hasattr(value, "__iter__")
            ):
                try:
                    arr = list(value)
                except Exception:
                    continue
                if len(arr) > MAX_SNAPSHOT_LEN:
                    arr = arr[:MAX_SNAPSHOT_LEN]
                try:
                    floats = [float(v) for v in arr]
                except (TypeError, ValueError):
                    continue
                self.plot.push_snapshot(label, floats, ts)

    def _refresh_table(self) -> None:
        if self.region.width == 0:
            return
        st = self.query_one("#side-table", DataTable)
        st.clear()
        for label, (_topic, _path, kind) in self._sources.items():
            series = self.plot.series.get(label)
            cur_text = "—"
            if isinstance(series, PlotSeries):
                stat = series.stats()
                if stat:
                    _, _, _, latest = stat
                    cur_text = format_value(latest)
            elif isinstance(series, SnapshotSeries):
                stat = series.stats()
                if stat:
                    mn, mx, ln = stat
                    cur_text = f"n={ln} [{format_value(mn)}…{format_value(mx)}]"
            suffix = " (snap)" if kind == "array" else ""
            st.add_row(_truncate(label + suffix, 28), cur_text, key=label)

    # -------- key actions ----------------------------------------------

    def action_toggle_pause(self) -> None:
        self.plot.paused = not self.plot.paused

    def action_wider(self) -> None:
        self.plot.window_seconds = min(self.plot.window_seconds * 1.5, 600.0)
        self.app_.push_status(f"window = {self.plot.window_seconds:.0f}s")

    def action_narrower(self) -> None:
        self.plot.window_seconds = max(self.plot.window_seconds / 1.5, 1.0)
        self.app_.push_status(f"window = {self.plot.window_seconds:.0f}s")

    def action_clear(self) -> None:
        self._sources.clear()
        self.plot.clear_series()
        self.app_.push_status("cleared all series")

    def action_toggle_legend(self) -> None:
        self.plot.show_legend = not self.plot.show_legend

    def action_delete_series(self) -> None:
        st = self.query_one("#side-table", DataTable)
        if st.cursor_row is None or not st.row_count:
            return
        try:
            row_key, _ = st.coordinate_to_cell_key((st.cursor_row, 0))
        except Exception:
            return
        if row_key is None:
            return
        label = str(row_key.value)
        self._sources.pop(label, None)
        self.plot.remove_series(label)

    def action_save_csv(self) -> None:
        if not self._sources:
            self.app_.push_status("no series to save")
            return
        out = Path.cwd() / f"rosight-{int(time.time())}.csv"
        try:
            with out.open("w", newline="") as f:
                w = csv.writer(f)
                w.writerow(["kind", "x", "label", "value"])
                for label in self._sources:
                    series = self.plot.series.get(label)
                    if isinstance(series, PlotSeries):
                        for ts, v in series.buffer.snapshot():
                            w.writerow(["time", ts, label, v])
                    elif isinstance(series, SnapshotSeries):
                        for i, v in enumerate(series.values):
                            w.writerow(["snapshot", i, label, v])
            self.app_.push_status(f"saved {out.name}")
        except Exception as e:
            self.app_.push_status(f"save failed: {e}")


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else "…" + s[-(n - 1) :]
