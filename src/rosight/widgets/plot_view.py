"""Terminal plotting widget backed by ``plotext``.

A :class:`PlotView` renders one or more series — either time-series
(:class:`PlotSeries`) or per-frame array snapshots (:class:`SnapshotSeries`)
— side by side. Time series are buffered in :class:`TimedRingBuffer`;
snapshots just hold the latest array. The widget samples and renders at a
configurable refresh rate.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from rosight.utils.ringbuffer import TimedRingBuffer


@dataclass
class PlotSeries:
    """A single plottable time series."""

    label: str
    color: str = "cyan"
    buffer: TimedRingBuffer[float] = field(default=None)  # type: ignore[assignment]
    visible: bool = True

    def __post_init__(self) -> None:
        if self.buffer is None:
            self.buffer = TimedRingBuffer(window=30.0, max_points=5000)

    def push(self, value: float, ts: float | None = None) -> None:
        self.buffer.append(ts if ts is not None else time.monotonic(), float(value))

    @property
    def latest(self) -> float | None:
        snap = self.buffer.snapshot()
        return snap[-1][1] if snap else None

    def stats(self) -> tuple[float, float, float, float] | None:
        snap = self.buffer.values()
        if not snap:
            return None
        return (min(snap), max(snap), sum(snap) / len(snap), snap[-1])


@dataclass
class SnapshotSeries:
    """Snapshot of a 1D numeric array — plotted as value-vs-index.

    Unlike :class:`PlotSeries` there is no history buffer: the widget redraws
    the latest array on every refresh. ``last_ts`` is used to age out stale
    series in the legend.
    """

    label: str
    color: str = "cyan"
    values: list[float] = field(default_factory=list)
    last_ts: float = 0.0
    visible: bool = True

    def set_latest(self, values: Sequence[float], ts: float | None = None) -> None:
        self.values = [float(v) for v in values]
        self.last_ts = ts if ts is not None else time.monotonic()

    def stats(self) -> tuple[float, float, int] | None:
        if not self.values:
            return None
        return (min(self.values), max(self.values), len(self.values))


_PALETTE = [
    "cyan",
    "magenta",
    "green",
    "yellow",
    "red",
    "blue",
    "bright_cyan",
    "bright_magenta",
    "bright_green",
    "bright_yellow",
]


def assign_color(index: int) -> str:
    return _PALETTE[index % len(_PALETTE)]


class PlotView(Static):
    """A Static widget that renders multi-series plots with plotext."""

    DEFAULT_CSS = """
    PlotView {
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    """

    paused: reactive[bool] = reactive(False)
    window_seconds: reactive[float] = reactive(30.0)
    show_legend: reactive[bool] = reactive(True)

    def __init__(self, **kwargs) -> None:
        super().__init__("", **kwargs)
        self.series: dict[str, PlotSeries | SnapshotSeries] = {}
        self._last_render: float = 0.0

    # ----- series management -------------------------------------------

    def add_series(self, label: str, color: str | None = None) -> PlotSeries:
        existing = self.series.get(label)
        if isinstance(existing, PlotSeries):
            return existing
        c = color or assign_color(len(self.series))
        s = PlotSeries(
            label=label,
            color=c,
            buffer=TimedRingBuffer(window=self.window_seconds, max_points=5000),
        )
        self.series[label] = s
        return s

    def add_snapshot_series(self, label: str, color: str | None = None) -> SnapshotSeries:
        existing = self.series.get(label)
        if isinstance(existing, SnapshotSeries):
            return existing
        c = color or assign_color(len(self.series))
        s = SnapshotSeries(label=label, color=c)
        self.series[label] = s
        return s

    def remove_series(self, label: str) -> None:
        self.series.pop(label, None)

    def clear_series(self) -> None:
        self.series.clear()

    def push(self, label: str, value: float, ts: float | None = None) -> None:
        s = self.series.get(label)
        if s is None:
            s = self.add_series(label)
        if not isinstance(s, PlotSeries):
            return
        if not self.paused:
            s.push(value, ts)

    def push_snapshot(
        self, label: str, values: Sequence[float], ts: float | None = None
    ) -> None:
        s = self.series.get(label)
        if s is None:
            s = self.add_snapshot_series(label)
        if not isinstance(s, SnapshotSeries):
            return
        if not self.paused:
            s.set_latest(values, ts)

    def watch_window_seconds(self, value: float) -> None:
        for s in self.series.values():
            if isinstance(s, PlotSeries):
                s.buffer.resize(window=value)

    # ----- rendering ----------------------------------------------------

    def on_mount(self) -> None:
        self.set_interval(1 / 15, self._refresh)

    def _refresh(self) -> None:
        # Don't burn 15 Hz worth of plotext rendering when the Plot tab is
        # hidden. We deliberately still let `PlotPanel._sample` collect
        # points in the background so the chart has history when the user
        # comes back.
        if self.region.width == 0:
            return
        now = time.monotonic()
        if now - self._last_render < (0.5 if self.paused else 1 / 15):
            return
        self._last_render = now
        self.update(self._build_content())

    def _build_content(self) -> Text | str:
        try:
            import plotext as plt
        except ImportError:  # pragma: no cover
            return "[bold red]plotext is not installed[/bold red]"

        size = self.size
        width = max(20, size.width - 2)
        height = max(8, size.height - 2)

        if not self.series:
            return Text(
                "no series — press [p] in the message tree to add a field "
                "(or [↵] on a numeric array)",
                style="italic dim",
                justify="center",
            )

        time_series: list[PlotSeries] = [
            s for s in self.series.values() if isinstance(s, PlotSeries) and s.visible
        ]
        snap_series: list[SnapshotSeries] = [
            s for s in self.series.values() if isinstance(s, SnapshotSeries) and s.visible
        ]

        plt.clf()
        plt.theme("clear")

        legend_lines: list[tuple[str, str, str]] = []  # label, color, current-value text

        if time_series and snap_series:
            plt.plotsize(width, height)
            try:
                plt.subplots(2, 1)
            except Exception:  # pragma: no cover — older plotext
                pass
            try:
                plt.subplot(1, 1)
            except Exception:  # pragma: no cover
                pass
            self._render_time(plt, time_series, legend_lines)
            try:
                plt.subplot(2, 1)
            except Exception:  # pragma: no cover
                pass
            self._render_snapshot(plt, snap_series, legend_lines)
        elif time_series:
            plt.plotsize(width, height)
            self._render_time(plt, time_series, legend_lines)
        elif snap_series:
            plt.plotsize(width, height)
            self._render_snapshot(plt, snap_series, legend_lines)
        else:
            # Series exist but all hidden — show legend only.
            for s in self.series.values():
                legend_lines.append((s.label, s.color, "(hidden)"))

        chart = plt.build() if (time_series or snap_series) else ""
        text = Text.from_ansi(chart) if chart else Text()
        if self.show_legend:
            if chart:
                text.append("\n")
            for label, color, cur in legend_lines:
                text.append("● ", style=color)
                text.append(f"{label} = {cur}  ", style="dim")
        if self.paused:
            text.append("\n[PAUSED] ", style="bold yellow")
        return text

    def _render_time(
        self,
        plt,
        series: list[PlotSeries],
        legend_lines: list[tuple[str, str, str]],
    ) -> None:
        any_data = False
        now = time.monotonic()
        for s in series:
            data = s.buffer.snapshot()
            if not data:
                legend_lines.append((s.label + " (t)", s.color, "—"))
                continue
            xs = [t - now for t, _ in data]
            ys = [v for _, v in data]
            plt.plot(xs, ys, color=s.color, label=s.label)
            any_data = True
            legend_lines.append((s.label + " (t)", s.color, f"{ys[-1]:.4g}"))
        plt.xlim(-self.window_seconds, 0)
        plt.xlabel("seconds")
        if not any_data:
            plt.text("waiting for data…", -self.window_seconds / 2, 0, color="white")

    def _render_snapshot(
        self,
        plt,
        series: list[SnapshotSeries],
        legend_lines: list[tuple[str, str, str]],
    ) -> None:
        any_data = False
        max_len = 0
        for s in series:
            if not s.values:
                legend_lines.append((s.label + " (snap)", s.color, "—"))
                continue
            xs = list(range(len(s.values)))
            plt.plot(xs, s.values, color=s.color, label=s.label)
            any_data = True
            max_len = max(max_len, len(s.values))
            stat = s.stats()
            if stat is not None:
                mn, mx, ln = stat
                legend_lines.append(
                    (s.label + " (snap)", s.color, f"len={ln} min={mn:.4g} max={mx:.4g}")
                )
        if max_len > 0:
            plt.xlim(0, max_len - 1)
        plt.xlabel("index")
        if not any_data:
            plt.text("waiting for data…", 0, 0, color="white")
