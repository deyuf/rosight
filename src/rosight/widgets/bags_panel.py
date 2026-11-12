"""Bag panel: record / play / inspect ROS 2 bag files via rosbag2_py."""

from __future__ import annotations

import atexit
import logging
import os
import shlex
import signal
import subprocess
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input, Static

from rosight.utils.datatable import fit_last_column, fit_last_column_when_ready, sync_table

if TYPE_CHECKING:
    from rosight.app import RosightApp

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Child-process lifecycle
#
# Children are started with ``start_new_session=True`` (see _CHILD_KW), so
# they are NOT in the terminal's foreground process group: closing the TUI,
# Ctrl+C, or a crash does not reach them, and a recorder would keep writing
# to disk after rosight exited. Every child is tracked here and stopped on
# panel unmount and, as a last resort, at interpreter exit.
# ---------------------------------------------------------------------------

_LIVE: dict[int, Any] = {}
# Bound at import so isinstance() keeps working even if ``subprocess.Popen``
# is later replaced (tests monkeypatch it; so do some debuggers).
_POPEN_CLS = subprocess.Popen


def _track(proc: Any) -> Any:
    _LIVE[id(proc)] = proc
    return proc


def _is_running(proc: Any) -> bool:
    try:
        return proc is not None and proc.poll() is None
    except Exception:
        return False


def _signal(proc: Any, sig: int) -> None:
    """Send ``sig`` to the child's whole process group when possible.

    ``ros2 bag`` may fork helpers, so the group is the right target. Only
    real ``Popen`` objects get ``killpg`` — anything else (test doubles)
    goes through its own ``send_signal``/``terminate``.
    """
    try:
        if isinstance(proc, _POPEN_CLS) and hasattr(os, "killpg"):
            try:
                os.killpg(proc.pid, sig)
                return
            except (ProcessLookupError, PermissionError, OSError):
                pass
        send = getattr(proc, "send_signal", None)
        if callable(send):
            send(sig)
        else:
            proc.terminate()
    except Exception:
        log.debug("signal %s to child failed", sig, exc_info=True)


def request_stop(proc: Any) -> None:
    """Ask a child to stop gracefully without blocking the UI.

    SIGINT is what ``ros2 bag record`` handles to flush and write
    ``metadata.yaml``; SIGTERM can leave an unreadable bag on some distros.
    """
    if _is_running(proc):
        _signal(proc, signal.SIGINT)


def stop_process(proc: Any, timeout: float = 5.0) -> None:
    """Stop a child, escalating SIGINT → SIGTERM → SIGKILL. Blocks up to
    roughly ``timeout + 3`` seconds; never raises."""
    if proc is None:
        return
    try:
        for sig, wait_s in (
            (signal.SIGINT, timeout),
            (signal.SIGTERM, 2.0),
            (signal.SIGKILL, 1.0),
        ):
            if not _is_running(proc):
                break
            _signal(proc, sig)
            wait = getattr(proc, "wait", None)
            if not callable(wait):
                break
            try:
                wait(timeout=wait_s)
            except subprocess.TimeoutExpired:
                continue
    except Exception:
        log.debug("stop_process failed", exc_info=True)
    finally:
        _LIVE.pop(id(proc), None)


def stop_all_children(timeout: float = 5.0) -> None:
    for proc in list(_LIVE.values()):
        stop_process(proc, timeout)


atexit.register(stop_all_children)


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
    BagsPanel Input { border-title-color: $text-muted; border-title-style: italic; }
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
        self.query_one("#record-args", Input).border_title = "record args"
        self.query_one("#play-path", Input).border_title = "bag to play / inspect"
        t = self.query_one("#procs", DataTable)
        t.add_columns("Process", "PID", "State", "Started")
        fit_last_column_when_ready(t)
        self.set_interval(1.0, self._refresh)

    def on_resize(self) -> None:
        fit_last_column_when_ready(self.query_one("#procs", DataTable))

    def running_processes(self) -> list[str]:
        """Labels of children still running ("record", "play")."""
        return [
            label
            for label, proc in (("record", self._record_proc), ("play", self._play_proc))
            if _is_running(proc)
        ]

    def on_unmount(self) -> None:
        # The app is closing (or the panel is being removed): make sure no
        # recorder/player outlives us. Blocking here is fine — it's bounded
        # and lets rosbag2 finalize the bag.
        for proc in (self._record_proc, self._play_proc):
            stop_process(proc)

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
    _CHILD_KW: ClassVar[dict[str, Any]] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "start_new_session": True,
    }

    def action_toggle_record(self) -> None:
        if _is_running(self._record_proc):
            request_stop(self._record_proc)
            self._set_recording(False)
            self.app_.notify("recording stopped", title="Bag")
            return
        raw_args = self.query_one("#record-args", Input).value.strip()
        try:
            # shlex.split handles quoted args ("-x '/scan.*'") and
            # ``--storage=mcap``-style flags that bare .split() would
            # otherwise pass through unchanged but inconsistently.
            args = shlex.split(raw_args) if raw_args else ["-a"]
        except ValueError as e:
            self.app_.notify(f"invalid record-args: {e}", severity="warning", title="Bag")
            return
        out_dir = self._record_output_dir()
        try:
            out_dir.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.app_.notify(f"can't create output dir: {e}", severity="error", title="Bag")
            return
        cmd = ["ros2", "bag", "record", "-o", str(out_dir), *args]
        try:
            self._record_proc = _track(subprocess.Popen(cmd, **self._CHILD_KW))
            self._set_recording(True)
            self.app_.notify(
                f"recording to {out_dir}\npress R or s to stop",
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
        # Defend against typos and stale paths — ros2 bag's own error
        # would otherwise scroll past the user in the detached log.
        bag_path = Path(path).expanduser()
        if not bag_path.exists():
            self.app_.notify(f"bag not found: {bag_path}", severity="warning", title="Bag")
            return
        if _is_running(self._play_proc):
            # Only one playback at a time; the previous one would otherwise
            # be orphaned and keep publishing in the background.
            request_stop(self._play_proc)
        try:
            self._play_proc = _track(
                subprocess.Popen(["ros2", "bag", "play", str(bag_path)], **self._CHILD_KW)
            )
            self.app_.notify(f"playing {bag_path.name}", title="Bag")
        except FileNotFoundError:
            self.app_.notify("ros2 CLI not found in PATH", severity="error")
        except Exception as e:
            self.app_.notify(f"play failed: {e}", severity="error")

    def _record_output_dir(self) -> Path:
        """Where to write ``ros2 bag record -o <here>``.

        Honors ``config.ui.bag_output_dir`` when configured; otherwise
        falls back to the current working directory. Extracted so tests
        can pin it to a tmp_path without touching the filesystem.
        """
        cfg = getattr(getattr(self.app_, "config", None), "ui", None)
        base = getattr(cfg, "bag_output_dir", None) or getattr(cfg, "export_dir", None)
        root = Path(base).expanduser() if base else Path.cwd()
        return (root / f"rosight-bag-{int(time.time())}").resolve()

    def action_stop(self) -> None:
        stopped = False
        for proc in (self._record_proc, self._play_proc):
            if _is_running(proc):
                request_stop(proc)
                stopped = True
        if stopped:
            self._set_recording(False)
            self.app_.notify("stopped", title="Bag")

    def action_info(self) -> None:
        path = self.query_one("#play-path", Input).value.strip()
        if not path:
            return
        bag_path = Path(path).expanduser()
        if not bag_path.exists():
            self.app_.notify(f"bag not found: {bag_path}", severity="warning", title="Bag")
            return
        try:
            res = subprocess.run(
                ["ros2", "bag", "info", str(bag_path)],
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
        recording = False
        rows = []
        for label, proc in (("record", self._record_proc), ("play", self._play_proc)):
            if proc is None:
                continue
            alive = _is_running(proc)
            if not alive:
                _LIVE.pop(id(proc), None)
            if label == "record" and alive:
                recording = True
            state = "running" if alive else f"exit {proc.returncode}"
            rows.append((label, (label, str(proc.pid), state, "—")))
        # Widths were fitted on the empty table at mount; refit whenever rows
        # change or the table showed a horizontal scrollbar.
        if sync_table(t, rows):
            fit_last_column(t)
        # Auto-revert the header if the recorder exited on its own
        # (e.g. SIGTERM from outside, disk full, ros2 crash).
        self._set_recording(recording)
