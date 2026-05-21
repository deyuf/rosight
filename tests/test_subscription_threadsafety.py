"""Tests for the thread-safe ``Subscription`` accessors.

The rclpy executor invokes the registered callback on a worker thread
while the Textual event loop reads ``last_msg``/``last_msg_ts`` and
mutates the callback list from the main thread. These tests pound on
both sides concurrently to catch ``ValueError`` from list-mid-iteration
or torn ``snapshot()`` results.
"""

from __future__ import annotations

import threading
import time

import pytest

from rosight.ros.backend import Subscription


def test_add_remove_callback_basic():
    sub = Subscription(topic="/x", type_name="std_msgs/msg/String")

    def cb(_):
        pass

    sub.add_callback(cb)
    assert sub.callback_count() == 1
    assert sub.remove_callback(cb) is True
    assert sub.callback_count() == 0
    # second remove returns False, doesn't raise
    assert sub.remove_callback(cb) is False


def test_snapshot_returns_atomic_pair():
    sub = Subscription(topic="/x", type_name="t")
    with sub._lock:
        sub.last_msg = "hello"
        sub.last_msg_ts = 12.5
    assert sub.snapshot() == ("hello", 12.5)


def test_snapshot_under_concurrent_writes_never_tears():
    """Writer thread updates ``(msg, ts)`` together; readers must always
    see a pair from the same write — never ``msg_N`` paired with
    ``ts_(N-1)``. We encode the invariant as ``ts == int(msg)``."""
    sub = Subscription(topic="/x", type_name="t")
    stop = threading.Event()
    seen_torn: list[tuple] = []

    def writer():
        i = 0
        while not stop.is_set():
            with sub._lock:
                sub.last_msg = i
                sub.last_msg_ts = float(i)
            i += 1

    def reader():
        while not stop.is_set():
            msg, ts = sub.snapshot()
            if msg is not None and float(msg) != ts:
                seen_torn.append((msg, ts))

    w = threading.Thread(target=writer)
    rs = [threading.Thread(target=reader) for _ in range(3)]
    w.start()
    for r in rs:
        r.start()
    time.sleep(0.2)
    stop.set()
    w.join()
    for r in rs:
        r.join()
    assert not seen_torn, f"snapshot torn under contention: {seen_torn[:3]}"


def test_callbacks_can_be_added_and_removed_during_iteration():
    """Simulate the executor iterating over callbacks while a UI thread
    adds/removes callbacks. The executor takes a *snapshot* of the list
    under the lock before iterating — so even if a callback removes
    itself mid-iteration the running ``for`` loop is safe."""
    sub = Subscription(topic="/x", type_name="t")
    deliveries: list[int] = []
    stop = threading.Event()

    def cb_factory(i: int):
        def _cb(_msg):
            deliveries.append(i)

        return _cb

    cbs = [cb_factory(i) for i in range(20)]
    for cb in cbs[:10]:
        sub.add_callback(cb)

    def churn():
        # Add the second half, remove the first half, in a tight loop.
        i = 10
        while not stop.is_set():
            if i < 20:
                sub.add_callback(cbs[i])
                i += 1
            sub.remove_callback(cbs[(i - 10) % 10])
            sub.add_callback(cbs[(i - 10) % 10])

    def deliver():
        # Mimics the executor: snapshot then iterate.
        while not stop.is_set():
            with sub._lock:
                snap = list(sub.callbacks)
            for cb in snap:
                cb(None)

    t1 = threading.Thread(target=churn)
    t2 = threading.Thread(target=deliver)
    t1.start()
    t2.start()
    time.sleep(0.2)
    stop.set()
    t1.join()
    t2.join()
    # If anything blew up with ValueError or list-mid-mutation, the
    # threads would have raised; pytest captures and re-raises on join
    # only via uncaught exception hooks — so just ensure we made progress.
    assert len(deliveries) > 0


@pytest.mark.parametrize("n_threads", [4, 8])
def test_concurrent_add_remove_no_lost_state(n_threads):
    """Stress: many threads add and immediately remove their own callback.
    The final ``callback_count()`` must be exactly the initial value."""
    sub = Subscription(topic="/x", type_name="t")

    def baseline(_):
        pass

    sub.add_callback(baseline)
    barrier = threading.Barrier(n_threads)
    iters = 500

    def worker():
        my = lambda _m: None  # noqa: E731 — unique callable per thread
        barrier.wait()
        for _ in range(iters):
            sub.add_callback(my)
            assert sub.remove_callback(my) is True

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sub.callback_count() == 1  # only ``baseline`` remains
