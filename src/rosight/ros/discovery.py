"""Background ROS graph discovery.

Before this module every panel (and the status bar) queried the ROS graph
on its own timer, synchronously on Textual's event loop. With N topics a
single ``list_topics`` costs ``2N + 1`` graph calls (names + per-topic
publisher/subscriber counts), and that was repeated by up to six callers
per second.

:class:`GraphMonitor` collects the graph once per period on a dedicated
thread and publishes an immutable :class:`GraphSnapshot`. Readers grab the
latest snapshot in O(1) and use :attr:`GraphSnapshot.generation` to skip
work when nothing changed.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GraphSnapshot:
    """Immutable view of the ROS graph at one point in time.

    ``generation`` increases by one each time the *content* changes, so a
    reader can compare generations instead of diffing lists. Generation 0
    means "nothing discovered yet" (used for the loading state).
    """

    topics: tuple[Any, ...] = ()
    nodes: tuple[Any, ...] = ()
    services: tuple[Any, ...] = ()
    actions: tuple[Any, ...] = ()
    generation: int = 0
    stamp: float = 0.0

    def content(self) -> tuple[tuple[Any, ...], ...]:
        return (self.topics, self.nodes, self.services, self.actions)


EMPTY_SNAPSHOT = GraphSnapshot()

# A collector returns (topics, nodes, services, actions).
Collector = Callable[[], tuple[Sequence[Any], Sequence[Any], Sequence[Any], Sequence[Any]]]


def next_snapshot(prev: GraphSnapshot, collect: Collector) -> GraphSnapshot:
    """Collect the graph and return a new snapshot, bumping the generation
    only if the content changed. Returns ``prev`` unchanged otherwise."""
    topics, nodes, services, actions = collect()
    content = (tuple(topics), tuple(nodes), tuple(services), tuple(actions))
    if prev.generation and content == prev.content():
        return prev
    return GraphSnapshot(
        *content,
        generation=prev.generation + 1,
        stamp=time.monotonic(),
    )


class GraphMonitor:
    """Periodically collects the ROS graph on a background thread."""

    def __init__(self, collect: Collector, period: float = 1.0) -> None:
        self._collect = collect
        self._period = max(0.05, float(period))
        self._snapshot = EMPTY_SNAPSHOT
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.errors = 0

    @property
    def latest(self) -> GraphSnapshot:
        with self._lock:
            return self._snapshot

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="rosight-graph-monitor", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        self._wake.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout)
        self._thread = None

    def request_refresh(self) -> None:
        """Wake the worker for an immediate collection (e.g. user pressed r)."""
        self._wake.set()

    def poll_once(self) -> GraphSnapshot:
        """Collect synchronously on the caller's thread. Used by tests and
        as the worker's loop body."""
        try:
            snap = next_snapshot(self.latest, self._collect)
        except Exception:
            self.errors += 1
            log.debug("graph collection failed", exc_info=True)
            return self.latest
        with self._lock:
            self._snapshot = snap
        return snap

    def _run(self) -> None:
        while not self._stop.is_set():
            self.poll_once()
            self._wake.wait(self._period)
            self._wake.clear()
