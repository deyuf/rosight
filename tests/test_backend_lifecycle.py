"""Backend lifecycle: bounded shutdown, executor health, restart, service timeouts."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from rosight.ros import introspection
from rosight.ros.backend import RosBackend


def _started_backend() -> RosBackend:
    b = RosBackend(shutdown_timeout=0.2)
    b._started = True
    b._node = MagicMock()
    return b


def test_executor_alive_false_when_not_started():
    assert RosBackend().executor_alive is False


def test_executor_alive_tracks_spin_thread():
    b = _started_backend()
    release = threading.Event()
    t = threading.Thread(target=release.wait, daemon=True)
    t.start()
    b._spin_thread = t
    assert b.executor_alive
    release.set()
    t.join()
    assert not b.executor_alive


def test_spin_error_is_recorded():
    b = _started_backend()
    b._executor = MagicMock()
    b._executor.spin.side_effect = RuntimeError("rmw exploded")
    b._spin()
    assert b.last_error == "RuntimeError: rmw exploded"


def test_stop_is_bounded_even_if_executor_thread_hangs():
    b = _started_backend()
    never = threading.Event()
    hung = threading.Thread(target=never.wait, daemon=True)
    hung.start()
    b._spin_thread = hung
    b._executor = MagicMock()
    t0 = time.monotonic()
    b.stop()
    elapsed = time.monotonic() - t0
    never.set()
    assert elapsed < 1.5, f"stop() hung for {elapsed:.2f}s"
    assert not b.started
    assert b._executor is None

    assert b._node is None


def test_stop_passes_timeout_to_executor_shutdown():
    b = _started_backend()
    ex = MagicMock()
    b._executor = ex
    b.stop()
    ex.shutdown.assert_called_once_with(timeout_sec=0.2)


def test_stop_stops_graph_monitor():
    b = _started_backend()
    graph = MagicMock()
    b._graph = graph
    b.stop()
    graph.stop.assert_called_once()
    assert b._graph is None


def test_stop_survives_destroy_node_failure():
    b = _started_backend()
    b._node.destroy_node.side_effect = RuntimeError("already gone")
    b.stop()
    assert not b.started


def test_restart_calls_stop_then_start(monkeypatch):
    b = RosBackend()
    calls: list[str] = []
    monkeypatch.setattr(b, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(b, "start", lambda: calls.append("start"))
    b.restart()
    assert calls == ["stop", "start"]


class _Future:
    def __init__(self, result=None, complete=True):
        self._result = result
        self._complete = complete
        self._cbs = []

    def add_done_callback(self, cb):
        if self._complete:
            cb(self)
        else:
            self._cbs.append(cb)

    def result(self):
        return self._result


def _service_backend(monkeypatch, future: _Future, available=True):
    monkeypatch.setattr(introspection, "get_service_class", lambda _t: object)
    b = _started_backend()
    client = MagicMock()
    client.wait_for_service.return_value = available
    client.call_async.return_value = future
    b._node.create_client.return_value = client
    return b, client


def test_call_service_returns_result(monkeypatch):
    resp = SimpleNamespace(ok=True)
    b, client = _service_backend(monkeypatch, _Future(resp))
    assert b.call_service("/srv", "std_srvs/srv/Trigger", object(), timeout=1.0) is resp
    b._node.destroy_client.assert_called_once_with(client)


def test_call_service_times_out_and_cleans_up(monkeypatch):
    b, client = _service_backend(monkeypatch, _Future(complete=False))
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        b.call_service("/srv", "std_srvs/srv/Trigger", object(), timeout=0.2)
    assert time.monotonic() - t0 < 1.0
    client.remove_pending_request.assert_called_once()
    b._node.destroy_client.assert_called_once_with(client)


def test_call_service_unavailable(monkeypatch):
    b, _client = _service_backend(monkeypatch, _Future(), available=False)
    with pytest.raises(TimeoutError, match="unavailable"):
        b.call_service("/srv", "std_srvs/srv/Trigger", object(), timeout=0.1)
