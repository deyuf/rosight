"""Modal screen that previews a ``sensor_msgs/Image`` topic live.

Subscribes via the existing :class:`RosBackend`, throttles rendering to
~5 Hz, decodes through :mod:`rosight.utils.image_decode`, and shows the
result via :mod:`textual_image` (which auto-picks kitty / sixel / unicode
half-block fallback depending on terminal).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from rosight.utils.image_decode import Colormap, decode_compressed_image, decode_image

if TYPE_CHECKING:
    from rosight.ros.backend import RosBackend

log = logging.getLogger(__name__)

_COMPRESSED_TYPES = {
    "sensor_msgs/msg/CompressedImage",
    "sensor_msgs/CompressedImage",
}
_RAW_TYPES = {
    "sensor_msgs/msg/Image",
    "sensor_msgs/Image",
}
IMAGE_TYPES = _COMPRESSED_TYPES | _RAW_TYPES

_REFRESH_HZ = 5.0
_COLORMAPS: tuple[Colormap, ...] = ("turbo", "viridis", "gray")


class ImagePreviewScreen(ModalScreen[None]):
    """Live image preview overlay for a single topic.

    Keys:
        space — pause/resume rendering
        s — save the current frame as a PNG to cwd
        m — cycle colormap (turbo → viridis → gray) for depth encodings
        q / esc — close
    """

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("q", "dismiss", "Close"),
        Binding("space", "toggle_pause", "Pause"),
        Binding("s", "save", "Save"),
        Binding("m", "cycle_colormap", "Colormap"),
    ]

    DEFAULT_CSS = """
    ImagePreviewScreen {
        align: center middle;
    }
    ImagePreviewScreen > Vertical {
        width: 90%;
        height: 90%;
        max-width: 200;
        max-height: 60;
        background: $panel;
        border: round $primary;
        padding: 1 2;
    }
    ImagePreviewScreen #img-header {
        height: 1;
        background: $boost;
        padding: 0 1;
    }
    ImagePreviewScreen #img-host {
        height: 1fr;
        align: center middle;
    }
    ImagePreviewScreen #img-footer {
        height: 1;
        color: $text 60%;
    }
    """

    def __init__(self, ros: RosBackend, topic: str, type_name: str) -> None:
        super().__init__()
        self.ros = ros
        self.topic = topic
        self.type_name = type_name
        self._compressed = type_name in _COMPRESSED_TYPES
        self._latest_msg: Any = None
        self._latest_msg_ts: float = 0.0
        self._paused: bool = False
        self._colormap_idx: int = 0
        self._owned_subscription: bool = False
        self._image_widget: Any = None  # textual_image.widget.Image lazily added
        self._last_decoded: Any = None  # PIL.Image, used for save

    # ----- lifecycle -------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"{self.topic}", id="img-header")
            yield Static("waiting for first frame…", id="img-host")
            yield Static(_footer_help(), id="img-footer")

    def on_mount(self) -> None:
        if self.ros is None or not getattr(self.ros, "started", False):
            self._set_header_warning("ROS backend not running")
            return
        # Reuse an existing subscription if any; otherwise own one.
        try:
            existing = self.ros.get_subscription(self.topic)
        except Exception:
            existing = None
        try:
            if existing is None:
                self.ros.subscribe(self.topic, self.type_name, on_message=self._on_msg)
                self._owned_subscription = True
            else:
                existing.callbacks.append(self._on_msg)
        except Exception:
            log.exception("image subscribe failed")
            self._set_header_warning("subscribe failed — see logs")
            return
        self.set_interval(1.0 / _REFRESH_HZ, self._render)

    def on_unmount(self) -> None:
        ros = self.ros
        if ros is None:
            return
        try:
            sub = ros.get_subscription(self.topic)
        except Exception:
            sub = None
        if sub is not None:
            # Detach our callback if still present.
            try:
                if self._on_msg in sub.callbacks:
                    sub.callbacks.remove(self._on_msg)
            except Exception:
                pass
            # Tear down the subscription only if we created it AND nobody
            # else is listening — otherwise leave it for the topics panel.
            if self._owned_subscription and not sub.callbacks:
                try:
                    ros.unsubscribe(self.topic)
                except Exception:
                    log.debug("unsubscribe on close failed", exc_info=True)

    # ----- callback (rclpy thread) ----------------------------------------

    def _on_msg(self, msg: Any) -> None:
        # Just stash the latest message; decode happens on the Textual loop.
        self._latest_msg = msg
        self._latest_msg_ts = time.monotonic()

    # ----- render (Textual loop) ------------------------------------------

    def _render(self) -> None:
        if self._paused:
            return
        msg = self._latest_msg
        if msg is None:
            return
        try:
            if self._compressed:
                img = decode_compressed_image(msg)
                encoding_label = (getattr(msg, "format", "") or "compressed").lower()
            else:
                img = decode_image(msg, colormap=_COLORMAPS[self._colormap_idx])
                encoding_label = (getattr(msg, "encoding", "") or "?").lower()
        except Exception:
            log.exception("image decode crashed for %s", self.topic)
            return
        if img is None:
            self._set_header_warning(f"unsupported encoding: {encoding_label}")
            return
        self._last_decoded = img
        self._mount_or_update_image(img)
        self._update_header(img, encoding_label)

    def _mount_or_update_image(self, img: Any) -> None:
        host = self.query_one("#img-host", Static)
        if self._image_widget is None:
            try:
                from textual_image.widget import Image as _Image
            except Exception:
                log.exception("textual-image not available")
                host.update("[bold red]textual-image not installed[/bold red]")
                return
            host.update("")
            widget = _Image(img)
            self._image_widget = widget
            try:
                host.mount(widget)
            except Exception:
                log.exception("could not mount image widget")
                return
        else:
            try:
                self._image_widget.image = img
            except Exception:
                log.exception("could not update image widget")

    # ----- header / footer formatting --------------------------------------

    def _update_header(self, img: Any, encoding_label: str) -> None:
        sub = None
        try:
            sub = self.ros.get_subscription(self.topic)
        except Exception:
            pass
        hz_text = bw_text = "—"
        if sub is not None:
            try:
                hz_text = f"{sub.rate.sample().hz:.1f} Hz"
                bw_text = _bw_text(sub.bandwidth.sample().bytes_per_sec)
            except Exception:
                pass
        cmap = _COLORMAPS[self._colormap_idx] if not self._compressed else "—"
        status = " · PAUSED" if self._paused else ""
        w, h = img.size
        text = (
            f"{self.topic}  ·  {encoding_label}  ·  {w}x{h}  "
            f"·  {hz_text}  ·  {bw_text}  ·  cmap={cmap}{status}"
        )
        self.query_one("#img-header", Static).update(text)

    def _set_header_warning(self, msg: str) -> None:
        try:
            self.query_one("#img-header", Static).update(f"{self.topic}  ·  {msg}")
        except Exception:
            pass

    # ----- key actions -----------------------------------------------------

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        if self._last_decoded is not None:
            try:
                self._update_header(self._last_decoded, "")
            except Exception:
                pass

    def action_cycle_colormap(self) -> None:
        if self._compressed:
            self.app.notify(
                "colormap doesn't apply to compressed images",
                title="Image",
                severity="information",
            )
            return
        self._colormap_idx = (self._colormap_idx + 1) % len(_COLORMAPS)
        # Force a re-render with the new colormap.
        self._render()

    def action_save(self) -> None:
        if self._last_decoded is None:
            self.app.notify("no frame yet", title="Image", severity="warning")
            return
        # Sanitize topic into a filename-safe stem.
        safe = self.topic.strip("/").replace("/", "_") or "image"
        out = Path.cwd() / f"rosight-{safe}-{int(time.time())}.png"
        try:
            self._last_decoded.save(out)
        except Exception as e:
            self.app.notify(f"save failed: {e}", title="Image", severity="error")
            return
        self.app.notify(f"saved {out.name}", title="Image")


# ----- helpers --------------------------------------------------------------


def _footer_help() -> str:
    return "[space] pause   [m] colormap   [s] save   [q]/[esc] close"


def _bw_text(bps: float) -> str:
    if bps >= 1e6:
        return f"{bps / 1e6:.1f} MB/s"
    if bps >= 1e3:
        return f"{bps / 1e3:.1f} kB/s"
    return f"{bps:.0f} B/s"
