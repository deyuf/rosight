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

from rosight.utils.datatable import fit_last_column_when_ready

if TYPE_CHECKING:
    from rosight.app import RosightApp

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

    _HEADER_IDLE = (
        "rosbag2 — [bold]R[/bold] record  ·  [bold]p[/bold] play  ·  [bold]i[/bold] bag info"
    )
    _HEADER_RECORDING = (
        "[bold red]● recording[/bold red]  ·  press [bold]R[/bold] or [bold]s[/bold] to stop"
    )

    def compose(self) -> ComposeResult:
        yield Static(self._HEADER_IDLE, id="header", markup=True)
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
    def app_(self) -> RosightApp:
        return self.app  # type: ignore[return-value]

    # ---- record / play -----------------------------------------------

    # Long-running children inherit a copy of the parent TTY stdin unless we
    # redirect it. While `ros2 bag record` is running, every keystroke the
    # user makes is delivered to *both* Textual and the recorder — Textual
    # sees a random subset of `1`-`9` and tab-switching looked "jumpy". The
    # recorder also echoed bytes back into the Input on its way out, which
    # showed up as random characters in the record-args box. `start_new_session`
    # additionally detaches the child from our controlling terminal so SIGINT
    # / window-size changes don't propagate to it.
    _CHILD_KW = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "start_new_session": True,
    }

    def action_toggle_record(self) -> None:
        if self._record_proc and self._record_proc.poll() is None:
            self._record_proc.terminate()
            self._set_recording(False)
            self.app_.notify("recording stopped", title="Bag")
            return
        args = self.query_one("#record-args", Input).value.split() or ["-a"]
        out_dir = Path.cwd() / f"rosight-bag-{int(time.time())}"
        cmd = ["ros2", "bag", "record", "-o", str(out_dir), *args]
        try:
            self._record_proc = subprocess.Popen(cmd, **self._CHILD_KW)
            self._set_recording(True)
            self.app_.notify(
                f"recording to {out_dir.name}\npress R or s to stop",
                title="Bag",
            )
        except FileNotFoundError:
            self.app_.notify("ros2 CLI not found in PATH", severity="error")
        except Exception as e:
            self.app_.notify(f"record failed: {e}", severity="error")

    def action_play(self) -> None:
        path = self.query_one("#play-path", Input).value.strip()
        if not path:
            self.app_.notify("set a bag path first", severity="warning")
            return
        try:
            self._play_proc = subprocess.Popen(["ros2", "bag", "play", path], **self._CHILD_KW)
            self.app_.notify(f"playing {path}", title="Bag")
        except Exception as e:
            self.app_.notify(f"play failed: {e}", severity="error")

    def action_stop(self) -> None:
        stopped = False
        for proc in (self._record_proc, self._play_proc):
            if proc and proc.poll() is None:
                proc.terminate()
                stopped = True
        if stopped:
            self._set_recording(False)
            self.app_.notify("stopped", title="Bag")

    def action_info(self) -> None:
        path = self.query_one("#play-path", Input).value.strip()
        if not path:
            return
        try:
            res = subprocess.run(
                ["ros2", "bag", "info", path],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            self.app_.notify(
                f"bag info: {len(res.stdout.splitlines())} lines (see log)",
                title="Bag",
            )
            log.info("bag info:\n%s", res.stdout)
        except Exception as e:
            self.app_.notify(f"info failed: {e}", severity="error")

    def _set_recording(self, recording: bool) -> None:
        """Swap the header text so the stop shortcut is visible during a record."""
        try:
            self.query_one("#header", Static).update(
                self._HEADER_RECORDING if recording else self._HEADER_IDLE
            )
        except Exception:
            pass

    def _refresh(self) -> None:
        if self.region.width == 0:
            return
        t = self.query_one("#procs", DataTable)
        t.clear()
        recording = False
        for label, proc in (("record", self._record_proc), ("play", self._play_proc)):
            if proc is None:
                continue
            alive = proc.poll() is None
            if label == "record" and alive:
                recording = True
            state = "running" if alive else f"exit {proc.returncode}"
            t.add_row(label, str(proc.pid), state, "—", key=label)
        # Auto-revert the header if the recorder exited on its own
        # (e.g. SIGTERM from outside, disk full, ros2 crash).
        self._set_recording(recording)
