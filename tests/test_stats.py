from __future__ import annotations

from lazyrosplus.ros.stats import BandwidthMonitor, RateMonitor, _heuristic_size


def test_rate_monitor_zero_when_empty():
    rm = RateMonitor(window=5.0)
    s = rm.sample(now=0.0)
    assert s.hz == 0.0
    assert s.samples == 0


def test_rate_monitor_computes_hz_at_10hz():
    rm = RateMonitor(window=5.0)
    for i in range(10):
        rm.tick(ts=i * 0.1)
    s = rm.sample(now=1.0)
    assert 9.0 <= s.hz <= 11.0
    assert s.samples == 10


def test_rate_monitor_evicts_old():
    rm = RateMonitor(window=1.0)
    rm.tick(ts=0.0)
    rm.tick(ts=0.5)
    rm.tick(ts=10.0)
    s = rm.sample(now=10.0)
    assert s.samples == 1


def test_bandwidth_monitor_average_size():
    bm = BandwidthMonitor(window=10.0)
    for i in range(5):
        bm.tick(100, ts=i * 1.0)
    s = bm.sample(now=4.0)
    assert s.samples == 5
    assert s.avg_msg_size == 100
    assert s.bytes_per_sec > 0


def test_heuristic_size_handles_primitives_and_collections():
    assert _heuristic_size(None) >= 1
    assert _heuristic_size(True) >= 1
    assert _heuristic_size(42) >= 1
    assert _heuristic_size(3.14) >= 1
    assert _heuristic_size("abc") >= 3
    assert _heuristic_size([1, 2, 3]) >= 3
    assert _heuristic_size({"k": 1}) >= 1


def test_heuristic_size_walks_msg(tiny_message):
    sz = _heuristic_size(tiny_message)
    # 6 floats * 8 bytes = 48 + small overhead
    assert sz >= 32
