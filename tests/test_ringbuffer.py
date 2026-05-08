from __future__ import annotations

import pytest

from lazyrosplus.utils.ringbuffer import RingBuffer, TimedRingBuffer


def test_ringbuffer_capacity_and_eviction():
    rb: RingBuffer[int] = RingBuffer(3)
    for i in range(5):
        rb.append(i)
    assert rb.snapshot() == [2, 3, 4]
    assert len(rb) == 3
    assert rb.latest() == 4


def test_ringbuffer_clear():
    rb: RingBuffer[int] = RingBuffer(3)
    rb.extend([1, 2, 3])
    rb.clear()
    assert rb.snapshot() == []
    assert rb.latest() is None


def test_ringbuffer_invalid_capacity():
    with pytest.raises(ValueError):
        RingBuffer(0)


def test_timed_ringbuffer_evicts_old_samples():
    tb: TimedRingBuffer[float] = TimedRingBuffer(window=10.0)
    tb.append(0.0, 1.0)
    tb.append(5.0, 2.0)
    tb.append(20.0, 3.0)  # this also evicts older than t-10
    snap = tb.snapshot()
    assert snap == [(20.0, 3.0)]


def test_timed_ringbuffer_preserves_recent():
    tb: TimedRingBuffer[float] = TimedRingBuffer(window=10.0)
    tb.append(100.0, 1.0)
    tb.append(105.0, 2.0)
    tb.append(108.0, 3.0)
    assert len(tb) == 3
    assert tb.values() == [1.0, 2.0, 3.0]


def test_timed_ringbuffer_resize_window_shrinks_history():
    tb: TimedRingBuffer[float] = TimedRingBuffer(window=10.0)
    tb.append(0.0, 1.0)
    tb.append(5.0, 2.0)
    tb.resize(window=2.0)
    # next append at t=10 will evict t=0 and t=5
    tb.append(10.0, 3.0)
    assert tb.values() == [3.0]


def test_timed_ringbuffer_invalid():
    with pytest.raises(ValueError):
        TimedRingBuffer(window=0)
    with pytest.raises(ValueError):
        TimedRingBuffer(window=1, max_points=0)
