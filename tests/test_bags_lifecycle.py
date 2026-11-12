"""Bag child-process lifecycle: graceful stop, escalation, cleanup on exit.

Regression: children were started with ``start_new_session=True`` and
never stopped, so ``ros2 bag record`` kept running after rosight quit.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time

import pytest

from rosight.widgets import bags_panel
from rosight.widgets.bags_panel import _LIVE, _track, request_stop, stop_process


class _FakeProc:
    """Ignores the first ``ignore`` signals, then exits."""

    def __init__(self, ignore: int = 0):
        self.pid = 999_999
        self.signals: list[int] = []
        self.returncode: int | None = None
        self._ignore = ignore

    def poll(self):
        return self.returncode

    def send_signal(self, sig):
        self.signals.append(sig)
        if len(self.signals) > self._ignore:
            self.returncode = -sig

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("fake", timeout)
        return self.returncode


def test_request_stop_sends_sigint_without_waiting():
    p = _FakeProc(ignore=5)
    request_stop(p)
    assert p.signals == [signal.SIGINT]


def test_request_stop_ignores_finished_process():
    p = _FakeProc()
    p.returncode = 0
    request_stop(p)
    assert p.signals == []


def test_stop_process_graceful_sigint_first():
    p = _track(_FakeProc())
    stop_process(p, timeout=0.1)
    assert p.signals == [signal.SIGINT]
    assert id(p) not in _LIVE


def test_stop_process_escalates_to_sigterm_then_sigkill():
    p = _FakeProc(ignore=2)
    stop_process(p, timeout=0.05)
    assert p.signals == [signal.SIGINT, signal.SIGTERM, signal.SIGKILL]


def test_stop_process_none_and_broken_objects_never_raise():
    stop_process(None)
    stop_process(object())  # no poll / wait at all


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_real_child_is_stopped_with_its_process_group():
    proc = _track(
        subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            start_new_session=True,
        )
    )
    t0 = time.monotonic()
    stop_process(proc, timeout=3)
    assert proc.poll() is not None
    assert time.monotonic() - t0 < 3


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")
def test_real_child_ignoring_sigint_is_terminated():
    code = "import signal,time; signal.signal(signal.SIGINT, signal.SIG_IGN); time.sleep(30)"
    proc = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    time.sleep(0.3)  # let it install the handler
    stop_process(proc, timeout=0.3)
    assert proc.returncode == -signal.SIGTERM


def test_stop_all_children_drains_registry():
    a, b = _track(_FakeProc()), _track(_FakeProc())
    bags_panel.stop_all_children(timeout=0.05)
    assert a.signals and b.signals
    assert id(a) not in _LIVE and id(b) not in _LIVE


@pytest.mark.asyncio
async def test_panel_unmount_stops_running_recorder(monkeypatch):
    pytest.importorskip("textual")
    from rosight.app import RosightApp
    from rosight.ros.backend import RosBackend

    fake = _FakeProc()
    monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: fake)
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one("TabbedContent").active = "bags"
        await pilot.pause()
        panel = pilot.app.query_one(bags_panel.BagsPanel)
        panel.action_toggle_record()
        assert fake.poll() is None
    # App exited → panel unmounted → recorder got SIGINT.
    assert fake.signals[:1] == [signal.SIGINT]
    assert fake.poll() is not None


@pytest.mark.asyncio
async def test_starting_new_playback_stops_previous(monkeypatch, tmp_path):
    pytest.importorskip("textual")
    from rosight.app import RosightApp
    from rosight.ros.backend import RosBackend

    procs = [_FakeProc(), _FakeProc()]
    it = iter(procs)
    monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: next(it))
    bag = tmp_path / "bag"
    bag.mkdir()
    app = RosightApp(ros=RosBackend())
    async with app.run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one("TabbedContent").active = "bags"
        await pilot.pause()
        panel = pilot.app.query_one(bags_panel.BagsPanel)
        panel.query_one("#play-path").value = str(bag)
        panel.action_play()
        panel.action_play()
        assert procs[0].signals == [signal.SIGINT]
        assert procs[1].signals == []
