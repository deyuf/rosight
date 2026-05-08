"""Terminal plotting widget backed by ``plotext``.

A :class:`PlotView` renders one or more :class:`PlotSeries` over a sliding
time window. Series data is buffered in :class:`TimedRingBuffer`; the widget
just samples and renders at a configurable refresh rate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from rich.text import Text
from textual.reactive import reactive
from textual.widgets import Static

from lazyrosplus.utils.ringbuffer import TimedRingBuffer


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
        self.series: dict[str, PlotSeries] = {}
        self._last_render: float = 0.0

    # ----- series management -------------------------------------------

    def add_series(self, label: str, color: str | None = None) -> PlotSeries:
        if label in self.series:
            return self.series[label]
        c = color or assign_color(len(self.series))
        s = PlotSeries(
            label=label,
            color=c,
            buffer=TimedRingBuffer(window=self.window_seconds, max_points=5000),
        )
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
        if not self.paused:
            s.push(value, ts)

    def watch_window_seconds(self, value: float) -> None:
        for s in self.series.values():
            s.buffer.resize(window=value)

    # ----- rendering ----------------------------------------------------

    def on_mount(self) -> None:
        self.set_interval(1 / 15, self._refresh)

    def _refresh(self) -> None:
        # Throttle slightly when paused to save CPU.
        now = time.monotonic()
        if now - self._last_render < (0.5 if self.paused else 1 / 15):
            return
        self._last_render = now
        self.update(self._render())

    def _render(self) -> Text:
        try:
            import plotext as plt
        except ImportError:  # pragma: no cover
            return Text("plotext is not installed", style="bold red")

        size = self.size
        width = max(20, size.width - 2)
        height = max(8, size.height - 2)

        if not self.series:
            return Text(
                "no series — press [p] in the message tree to add a field",
                style="italic dim",
                justify="center",
            )

        plt.clf()
        plt.theme("clear")
        plt.plotsize(width, height)
        any_data = False
        now = time.monotonic()
        legend_lines: list[tuple[str, str, float | None]] = []
        for s in self.series.values():
            if not s.visible:
                continue
            data = s.buffer.snapshot()
            if not data:
                legend_lines.append((s.label, s.color, None))
                continue
            xs = [t - now for t, _ in data]  # seconds-from-now (negative)
            ys = [v for _, v in data]
            plt.plot(xs, ys, color=s.color, label=s.label)
            any_data = True
            legend_lines.append((s.label, s.color, ys[-1]))

        plt.xlim(-self.window_seconds, 0)
        plt.xlabel("seconds")
        if not any_data:
            plt.text("waiting for data…", -self.window_seconds / 2, 0, color="white")

        chart = plt.build()
        text = Text.from_ansi(chart)
        if self.show_legend:
            text.append("\n")
            for label, color, latest in legend_lines:
                cur = "—" if latest is None else f"{latest:.4g}"
                text.append("● ", style=color)
                text.append(f"{label} = {cur}  ", style="dim")
        if self.paused:
            text.append("\n[PAUSED] ", style="bold yellow")
        return text
