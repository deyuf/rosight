"""Thread-safe ring buffers used by stats and plot panels."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable, Iterator
from typing import Generic, TypeVar

T = TypeVar("T")


class RingBuffer(Generic[T]):
    """A bounded FIFO buffer with O(1) append and snapshot copy.

    Designed for the producer/consumer split between rclpy executor threads
    (push) and the Textual main loop (snapshot for rendering).
    """

    __slots__ = ("_dq", "_lock", "capacity")

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._dq: deque[T] = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def append(self, item: T) -> None:
        with self._lock:
            self._dq.append(item)

    def extend(self, items: Iterable[T]) -> None:
        with self._lock:
            self._dq.extend(items)

    def clear(self) -> None:
        with self._lock:
            self._dq.clear()

    def snapshot(self) -> list[T]:
        """Return a stable copy of the current contents."""
        with self._lock:
            return list(self._dq)

    def latest(self) -> T | None:
        with self._lock:
            return self._dq[-1] if self._dq else None

    def __len__(self) -> int:
        with self._lock:
            return len(self._dq)

    def __iter__(self) -> Iterator[T]:
        return iter(self.snapshot())


class TimedRingBuffer(Generic[T]):
    """Ring buffer that also evicts items older than ``window`` seconds.

    Items are stored as (timestamp, value) tuples. The buffer also enforces
    ``max_points`` so memory stays bounded for very high-frequency streams.
    """

    __slots__ = ("_dq", "_lock", "max_points", "window")

    def __init__(self, window: float, max_points: int = 100_000) -> None:
        if window <= 0:
            raise ValueError("window must be positive")
        if max_points <= 0:
            raise ValueError("max_points must be positive")
        self.window = float(window)
        self.max_points = int(max_points)
        self._dq: deque[tuple[float, T]] = deque(maxlen=max_points)
        self._lock = threading.Lock()

    def append(self, ts: float, value: T) -> None:
        with self._lock:
            self._dq.append((ts, value))
            self._evict(ts)

    def _evict(self, now: float) -> None:
        cutoff = now - self.window
        dq = self._dq
        while dq and dq[0][0] < cutoff:
            dq.popleft()

    def snapshot(self) -> list[tuple[float, T]]:
        with self._lock:
            return list(self._dq)

    def values(self) -> list[T]:
        with self._lock:
            return [v for _, v in self._dq]

    def times(self) -> list[float]:
        with self._lock:
            return [t for t, _ in self._dq]

    def clear(self) -> None:
        with self._lock:
            self._dq.clear()

    def resize(self, window: float | None = None, max_points: int | None = None) -> None:
        with self._lock:
            if window is not None:
                if window <= 0:
                    raise ValueError("window must be positive")
                self.window = float(window)
            if max_points is not None:
                if max_points <= 0:
                    raise ValueError("max_points must be positive")
                self.max_points = int(max_points)
                # rebuild deque with new max
                self._dq = deque(self._dq, maxlen=self.max_points)

    def __len__(self) -> int:
        with self._lock:
            return len(self._dq)
