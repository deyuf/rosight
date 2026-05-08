"""Hz / bandwidth / delay accumulators (no rclpy dependency)."""

from __future__ import annotations

import statistics
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True, slots=True)
class RateSample:
    hz: float
    jitter_ms: float
    samples: int


@dataclass(frozen=True, slots=True)
class BandwidthSample:
    bytes_per_sec: float
    avg_msg_size: float
    samples: int


class RateMonitor:
    """Sliding-window publication rate monitor."""

    __slots__ = ("_lock", "_max_samples", "_times", "_window")

    def __init__(self, window: float = 5.0, max_samples: int = 4096) -> None:
        self._window = window
        self._max_samples = max_samples
        self._times: deque[float] = deque(maxlen=max_samples)
        self._lock = Lock()

    def tick(self, ts: float | None = None) -> None:
        t = ts if ts is not None else time.monotonic()
        with self._lock:
            self._times.append(t)
            self._evict(t)

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        while self._times and self._times[0] < cutoff:
            self._times.popleft()

    def sample(self, now: float | None = None) -> RateSample:
        t = now if now is not None else time.monotonic()
        with self._lock:
            self._evict(t)
            n = len(self._times)
            if n < 2:
                return RateSample(hz=0.0, jitter_ms=0.0, samples=n)
            span = self._times[-1] - self._times[0]
            hz = (n - 1) / span if span > 0 else 0.0
            deltas = [(self._times[i] - self._times[i - 1]) * 1000.0 for i in range(1, n)]
            jitter = statistics.stdev(deltas) if len(deltas) >= 2 else 0.0
        return RateSample(hz=hz, jitter_ms=jitter, samples=n)

    def reset(self) -> None:
        with self._lock:
            self._times.clear()


class BandwidthMonitor:
    """Sliding-window byte-rate monitor."""

    __slots__ = ("_events", "_lock", "_max_samples", "_window")

    def __init__(self, window: float = 5.0, max_samples: int = 4096) -> None:
        self._window = window
        self._max_samples = max_samples
        self._events: deque[tuple[float, int]] = deque(maxlen=max_samples)
        self._lock = Lock()

    def tick(self, n_bytes: int, ts: float | None = None) -> None:
        t = ts if ts is not None else time.monotonic()
        with self._lock:
            self._events.append((t, max(0, int(n_bytes))))
            self._evict(t)

    def _evict(self, now: float) -> None:
        cutoff = now - self._window
        ev = self._events
        while ev and ev[0][0] < cutoff:
            ev.popleft()

    def sample(self, now: float | None = None) -> BandwidthSample:
        t = now if now is not None else time.monotonic()
        with self._lock:
            self._evict(t)
            ev = list(self._events)
        if not ev:
            return BandwidthSample(0.0, 0.0, 0)
        total_bytes = sum(b for _, b in ev)
        span = max(self._window, ev[-1][0] - ev[0][0]) if len(ev) > 1 else self._window
        return BandwidthSample(
            bytes_per_sec=total_bytes / span if span > 0 else 0.0,
            avg_msg_size=total_bytes / len(ev),
            samples=len(ev),
        )

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


def estimate_msg_size(msg: object) -> int:
    """Best-effort serialised-size estimate without serialising.

    Tries ``rclpy.serialization.serialize_message`` if available; falls back
    to a recursive byte-count heuristic. Used only for display.
    """
    try:  # pragma: no cover — needs rclpy
        from rclpy.serialization import serialize_message  # type: ignore

        return len(serialize_message(msg))
    except Exception:
        return _heuristic_size(msg)


def _heuristic_size(value: object, _depth: int = 0) -> int:
    if _depth > 10:
        return 0
    if value is None:
        return 1
    if isinstance(value, bool):
        return 1
    if isinstance(value, int):
        return 8
    if isinstance(value, float):
        return 8
    if isinstance(value, (bytes, bytearray)):
        return len(value)
    if isinstance(value, str):
        return len(value.encode("utf-8")) + 4
    if isinstance(value, (list, tuple)):
        return 4 + sum(_heuristic_size(v, _depth + 1) for v in value)
    # ROS message: iterate __slots__ if present
    slots = getattr(value, "__slots__", None)
    if slots:
        return sum(_heuristic_size(getattr(value, s, None), _depth + 1) for s in slots)
    if hasattr(value, "__dict__"):
        return sum(_heuristic_size(v, _depth + 1) for v in vars(value).values())
    return 16
