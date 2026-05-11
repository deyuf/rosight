"""Bag panel: record / play / inspect ROS 2 bag files via rosbag2_py."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input, Static

from lazyrosplus.utils.datatable import fit_last_column_when_ready

if TYPE_CHECKING:
    from lazyrosplus.app import LazyrosPlusApp

log = logging.getLogger(__name__)


class BagsPanel(Vertical):
    """Manage rosbag2 record/play subprocesses.

    The panel deliberately spawns the ``ros2 bag`` CLI rather than using the
    rosbag2_py API directly: it keeps the implementation portable across ROS
    distros and avoids tying the recorder lifecycle to the TUI process.
    """

    BINDINGS = [
        Binding("R", "toggle_record", "Record"),
        Binding("p", "play", "Play"),
        Binding("s", "stop", "Stop"),
        Binding("i", "info", "Info"),
    ]

    DEFAULT_CSS = """
    BagsPanel { layout: vertical; padding: 1; }
    BagsPanel #header { background: $boost; padding: 0 1; }
    BagsPanel #procs { height: 1fr; }
    """

    bag_dir: reactive[str] = reactive(".")

    def __init__(self) -> None:
        super().__init__()
        self._record_proc: subprocess.Popen | None = None
        self._play_proc: subprocess.Popen | None = None

    def compose(self) -> ComposeResult:
        yield Static(
            "rosbag2 — capital R to record selected topics, p to play",
            id="header",
        )
        yield Input(
            value="-a",
            placeholder="extra args (e.g. /odom /scan, or -a for all)",
            id="record-args",
        )
        yield Input(
            value="",
            placeholder="bag dir to play (path)…",
            id="play-path",
        )
        yield DataTable(id="procs", cursor_type="row")

    def on_mount(self) -> None:
        t = self.query_one("#procs", DataTable)
        t.add_columns("Process", "PID", "State", "Started")
        fit_last_column_when_ready(t)
        self.set_interval(1.0, self._refresh)

    def on_resize(self) -> None:
        fit_last_column_when_ready(self.query_one("#procs", DataTable))

    @property
    def app_(self) -> LazyrosPlusApp:
        return self.app  # type: ignore[return-value]

    # ---- record / play -----------------------------------------------

    def action_toggle_record(self) -> None:
        if self._record_proc and self._record_proc.poll() is None:
            self._record_proc.terminate()
            self.app_.push_status("recording stopped")
            return
        args = self.query_one("#record-args", Input).value.split() or ["-a"]
        out_dir = Path.cwd() / f"lazyrosplus-bag-{int(time.time())}"
        cmd = ["ros2", "bag", "record", "-o", str(out_dir), *args]
        try:
            self._record_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.app_.push_status(f"recording to {out_dir.name}")
        except FileNotFoundError:
            self.app_.push_status("ros2 CLI not found in PATH")
        except Exception as e:
            self.app_.push_status(f"record failed: {e}")

    def action_play(self) -> None:
        path = self.query_one("#play-path", Input).value.strip()
        if not path:
            self.app_.push_status("set a bag path first")
            return
        try:
            self._play_proc = subprocess.Popen(
                ["ros2", "bag", "play", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.app_.push_status(f"playing {path}")
        except Exception as e:
            self.app_.push_status(f"play failed: {e}")

    def action_stop(self) -> None:
        for proc in (self._record_proc, self._play_proc):
            if proc and proc.poll() is None:
                proc.terminate()

    def action_info(self) -> None:
        path = self.query_one("#play-path", Input).value.strip()
        if not path:
            return
        try:
            res = subprocess.run(
                ["ros2", "bag", "info", path],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.app_.push_status(f"bag info: {len(res.stdout.splitlines())} lines (see log)")
            log.info("bag info:\n%s", res.stdout)
        except Exception as e:
            self.app_.push_status(f"info failed: {e}")

    def _refresh(self) -> None:
        if self.region.width == 0:
            return
        t = self.query_one("#procs", DataTable)
        t.clear()
        for label, proc in (("record", self._record_proc), ("play", self._play_proc)):
            if proc is None:
                continue
            state = "running" if proc.poll() is None else f"exit {proc.returncode}"
            t.add_row(label, str(proc.pid), state, "—", key=label)
