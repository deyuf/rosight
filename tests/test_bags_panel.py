"""Tests for the bags panel's input handling.

Focus on the recently-added robustness:

* ``record-args`` is parsed with ``shlex.split`` (so quoted args and
  ``--storage=mcap`` survive intact).
* ``play``/``info`` reject non-existent paths up front instead of
  fire-and-forget subprocess.
* The output directory honors ``config.ui.bag_output_dir`` when set.

Subprocess is patched out — we never want CI launching real
``ros2 bag``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("textual")

from dataclasses import replace

from rosight.app import RosightApp
from rosight.ros.backend import RosBackend
from rosight.widgets.bags_panel import BagsPanel


def _app() -> RosightApp:
    return RosightApp(ros=RosBackend())


@pytest.mark.asyncio
async def test_record_args_use_shlex(monkeypatch):
    """Quoted args and ``--key=val`` survive intact through shlex."""
    captured: dict = {}

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(pid=123, poll=lambda: None, terminate=lambda: None, returncode=0)

    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one("TabbedContent").active = "bags"
        await pilot.pause()
        panel = pilot.app.query_one(BagsPanel)
        # Quoted multi-word arg + flag-with-equals.
        panel.query_one("#record-args").value = "-x '/scan.*' --storage=mcap"
        monkeypatch.setattr("subprocess.Popen", fake_popen)
        panel.action_toggle_record()
        await pilot.pause()
        # cmd is: ["ros2", "bag", "record", "-o", <out_dir>, *args]
        cmd = captured["cmd"]
        assert cmd[:4] == ["ros2", "bag", "record", "-o"]
        # The shlex.split must keep the quoted regex as ONE token and
        # ``--storage=mcap`` as ONE token.
        tail = cmd[5:]
        assert "-x" in tail
        assert "/scan.*" in tail  # quotes stripped, value preserved
        assert "--storage=mcap" in tail
        # cleanup
        panel._record_proc = None


@pytest.mark.asyncio
async def test_record_args_malformed_quotes_notifies(monkeypatch):
    """Unbalanced quotes shouldn't blow up — shlex raises ValueError,
    which we catch and notify."""
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one("TabbedContent").active = "bags"
        await pilot.pause()
        panel = pilot.app.query_one(BagsPanel)
        panel.query_one("#record-args").value = "-x 'unterminated"
        notes: list = []
        pilot.app.notify = lambda *a, **kw: notes.append((a, kw))  # type: ignore[method-assign]
        # Popen must never be called when args parsing fails.
        monkeypatch.setattr(
            "subprocess.Popen",
            MagicMock(side_effect=AssertionError("Popen should not be called")),
        )
        panel.action_toggle_record()
        await pilot.pause()
        body = " ".join(str(a[0]) for a, _ in notes)
        assert "invalid record-args" in body


@pytest.mark.asyncio
async def test_play_rejects_missing_path(monkeypatch):
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one("TabbedContent").active = "bags"
        await pilot.pause()
        panel = pilot.app.query_one(BagsPanel)
        panel.query_one("#play-path").value = "/definitely/not/a/real/bag"
        notes: list = []
        pilot.app.notify = lambda *a, **kw: notes.append((a, kw))  # type: ignore[method-assign]
        # Popen must never be called for a non-existent bag.
        monkeypatch.setattr(
            "subprocess.Popen",
            MagicMock(side_effect=AssertionError("Popen should not be called")),
        )
        panel.action_play()
        body = " ".join(str(a[0]) for a, _ in notes)
        assert "not found" in body


@pytest.mark.asyncio
async def test_play_existing_path_launches_subprocess(monkeypatch, tmp_path):
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one("TabbedContent").active = "bags"
        await pilot.pause()
        panel = pilot.app.query_one(BagsPanel)
        # A bag is a directory in rosbag2 — any extant path is enough
        # for our pre-check.
        bag = tmp_path / "fake.bag"
        bag.mkdir()
        panel.query_one("#play-path").value = str(bag)
        called: dict = {}

        def fake_popen(cmd, **kw):
            called["cmd"] = cmd
            return SimpleNamespace(pid=42, poll=lambda: None, terminate=lambda: None)

        monkeypatch.setattr("subprocess.Popen", fake_popen)
        panel.action_play()
        assert called["cmd"][:3] == ["ros2", "bag", "play"]
        assert called["cmd"][3] == str(bag)


@pytest.mark.asyncio
async def test_record_output_dir_honors_config(monkeypatch, tmp_path):
    """When ``config.ui.bag_output_dir`` is set, recordings go there."""
    captured: dict = {}

    def fake_popen(cmd, **kw):
        captured["cmd"] = cmd
        return SimpleNamespace(pid=1, poll=lambda: None, terminate=lambda: None, returncode=0)

    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one("TabbedContent").active = "bags"
        await pilot.pause()
        # Inject the override — UIConfig is frozen, so build a new one.
        pilot.app.config = replace(
            pilot.app.config, ui=replace(pilot.app.config.ui, bag_output_dir=str(tmp_path))
        )
        panel = pilot.app.query_one(BagsPanel)
        monkeypatch.setattr("subprocess.Popen", fake_popen)
        panel.action_toggle_record()
        await pilot.pause()
        out_dir = captured["cmd"][4]  # the "-o" target
        assert out_dir.startswith(str(tmp_path))
        # cleanup
        panel._record_proc = None


@pytest.mark.asyncio
async def test_info_rejects_missing_path(monkeypatch):
    async with _app().run_test(headless=True, size=(120, 30)) as pilot:
        await pilot.pause()
        pilot.app.query_one("TabbedContent").active = "bags"
        await pilot.pause()
        panel = pilot.app.query_one(BagsPanel)
        panel.query_one("#play-path").value = "/missing/path"
        notes: list = []
        pilot.app.notify = lambda *a, **kw: notes.append((a, kw))  # type: ignore[method-assign]
        monkeypatch.setattr(
            "subprocess.run",
            MagicMock(side_effect=AssertionError("subprocess.run should not be called")),
        )
        panel.action_info()
        body = " ".join(str(a[0]) for a, _ in notes)
        assert "not found" in body
