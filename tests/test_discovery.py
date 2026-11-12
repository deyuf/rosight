"""Tests for the background graph monitor and GraphSnapshot generations."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock

from rosight.ros.backend import NodeInfo, RosBackend, TopicInfo
from rosight.ros.discovery import EMPTY_SNAPSHOT, GraphMonitor, next_snapshot


def _collector(state: dict):
    def collect():
        state["calls"] = state.get("calls", 0) + 1
        return state["topics"], state.get("nodes", []), [], []

    return collect


def test_next_snapshot_bumps_generation_only_on_change():
    state = {"topics": [TopicInfo("/a", ("t",))]}
    s1 = next_snapshot(EMPTY_SNAPSHOT, _collector(state))
    assert s1.generation == 1
    s2 = next_snapshot(s1, _collector(state))
    assert s2 is s1  # identical content → same object, same generation
    state["topics"] = [TopicInfo("/a", ("t",)), TopicInfo("/b", ("t",))]
    s3 = next_snapshot(s2, _collector(state))
    assert s3.generation == 2
    assert [t.name for t in s3.topics] == ["/a", "/b"]


def test_empty_graph_still_leaves_loading_state():
    """An empty graph on first collection must move generation off 0, so
    panels can tell "discovering…" from "nothing on this domain"."""
    s = next_snapshot(EMPTY_SNAPSHOT, lambda: ([], [], [], []))
    assert s.generation == 1


def test_monitor_thread_collects_and_stops():
    state = {"topics": [TopicInfo("/a", ("t",))]}
    mon = GraphMonitor(_collector(state), period=0.05)
    mon.start()
    try:
        deadline = time.monotonic() + 2
        while mon.latest.generation == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert mon.latest.generation == 1
        state["nodes"] = [NodeInfo("n", "/")]
        deadline = time.monotonic() + 2
        while mon.latest.generation < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert mon.latest.generation == 2
    finally:
        mon.stop(timeout=1)
    assert not mon.running


def test_request_refresh_wakes_worker_early():
    state = {"topics": []}
    mon = GraphMonitor(_collector(state), period=30.0)  # would sleep 30 s
    mon.start()
    try:
        deadline = time.monotonic() + 2
        while state.get("calls", 0) < 1 and time.monotonic() < deadline:
            time.sleep(0.01)
        before = state["calls"]
        mon.request_refresh()
        deadline = time.monotonic() + 2
        while state["calls"] == before and time.monotonic() < deadline:
            time.sleep(0.01)
        assert state["calls"] > before, "request_refresh did not wake the worker"
    finally:
        t0 = time.monotonic()
        mon.stop(timeout=2)
        assert time.monotonic() - t0 < 1.0, "stop() must not wait out the period"


def test_collector_errors_keep_last_good_snapshot():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("dds hiccup")
        return [TopicInfo("/a", ("t",))], [], [], []

    mon = GraphMonitor(flaky, period=1.0)
    good = mon.poll_once()
    assert good.generation == 1
    assert mon.poll_once() is good
    assert mon.errors == 1


def test_backend_snapshot_empty_when_not_started():
    assert RosBackend().graph_snapshot() is EMPTY_SNAPSHOT


def test_backend_sync_snapshot_generation_stable():
    """Mock backends (no monitor thread) collect synchronously but must
    still keep the generation stable while the graph is unchanged."""
    b = RosBackend()
    b._node = MagicMock()
    b._started = True
    b._node.get_topic_names_and_types.return_value = [("/chatter", ["std_msgs/msg/String"])]
    b._node.count_publishers.return_value = 1
    b._node.count_subscribers.return_value = 0
    b._node.get_node_names_and_namespaces.return_value = [("talker", "/")]
    b._node.get_service_names_and_types.return_value = []
    s1 = b.graph_snapshot()
    s2 = b.graph_snapshot()
    assert s1.generation == s2.generation == 1
    assert [t.name for t in s1.topics] == ["/chatter"]
    b._node.get_node_names_and_namespaces.return_value = [("talker", "/"), ("x", "/")]
    assert b.graph_snapshot().generation == 2


def test_backend_uses_monitor_snapshot_when_running():
    b = RosBackend()
    b._started = True
    sentinel = object()
    b._graph = MagicMock(latest=sentinel)
    assert b.graph_snapshot() is sentinel
    b.request_graph_refresh()
    b._graph.request_refresh.assert_called_once()


def test_monitor_poll_is_thread_safe_with_readers():
    state = {"topics": [TopicInfo("/a", ("t",))]}
    mon = GraphMonitor(_collector(state), period=0.01)
    stop = threading.Event()
    errors: list[Exception] = []

    def reader():
        while not stop.is_set():
            try:
                snap = mon.latest
                assert len(snap.content()) == 4
            except Exception as e:  # pragma: no cover - failure path
                errors.append(e)

    readers = [threading.Thread(target=reader) for _ in range(4)]
    for r in readers:
        r.start()
    mon.start()
    time.sleep(0.2)
    stop.set()
    mon.stop()
    for r in readers:
        r.join()
    assert not errors
