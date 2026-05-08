"""TF panel: subscribes to /tf and /tf_static and visualises the frame tree."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Static, Tree

if TYPE_CHECKING:
    from lazyros.app import LazyrosApp
    from lazyros.ros.backend import RosBackend

log = logging.getLogger(__name__)


class TfPanel(Vertical):
    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
    ]

    DEFAULT_CSS = """
    TfPanel { layout: horizontal; }
    TfPanel > #left { width: 50%; min-width: 30; border-right: solid $primary 30%; }
    TfPanel > #right { width: 1fr; padding: 0 1; }
    TfPanel Tree { height: 1fr; }
    """

    def __init__(self) -> None:
        super().__init__()
        # parent_frame -> set(child_frame)
        self._edges: dict[str, set[str]] = {}
        self._stamps: dict[tuple[str, str], float] = {}
        self._latest: dict[tuple[str, str], object] = {}
        self._subscribed = False

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Static("TF tree (auto-refreshing)", id="tf-header")
            yield Tree("/", id="tf-tree")
        with Vertical(id="right"):
            yield Static("Highlight a frame to see latest transform", id="tf-detail")

    def on_mount(self) -> None:
        self.set_interval(1.0, self._update_tree)

    @property
    def ros(self) -> RosBackend | None:
        return getattr(self.app, "ros", None)

    @property
    def app_(self) -> LazyrosApp:
        return self.app  # type: ignore[return-value]

    def _ensure_subscribed(self) -> None:
        if self._subscribed:
            return
        ros = self.ros
        if ros is None or not ros.started:
            return
        try:
            ros.subscribe("/tf", "tf2_msgs/msg/TFMessage", on_message=self._on_tf)
            ros.subscribe(
                "/tf_static",
                "tf2_msgs/msg/TFMessage",
                on_message=self._on_tf,
            )
            self._subscribed = True
        except Exception:
            log.exception("tf subscribe failed")

    def _on_tf(self, msg: object) -> None:
        try:
            transforms = getattr(msg, "transforms", None) or []
        except Exception:
            return
        now = time.monotonic()
        for t in transforms:
            try:
                parent = getattr(getattr(t, "header", None), "frame_id", "")
                child = getattr(t, "child_frame_id", "")
            except Exception:
                continue
            if not parent or not child:
                continue
            self._edges.setdefault(parent, set()).add(child)
            self._stamps[(parent, child)] = now
            self._latest[(parent, child)] = t

    def action_refresh(self) -> None:
        self._update_tree()

    def _update_tree(self) -> None:
        self._ensure_subscribed()
        tree = self.query_one("#tf-tree", Tree)
        tree.clear()
        # Identify roots: frames that appear as parents but never as children.
        children = {c for kids in self._edges.values() for c in kids}
        roots = sorted({p for p in self._edges if p not in children})
        if not roots and not self._edges:
            tree.root.label = Text("(no /tf data yet)", style="dim")
            return
        for root in roots or list(self._edges.keys())[:1]:
            self._add_subtree(tree.root, root, set(), depth=0)
        tree.root.expand_all()

    def _add_subtree(self, parent_node, frame: str, seen: set, depth: int) -> None:
        if frame in seen or depth > 20:
            return
        seen = seen | {frame}
        kids = sorted(self._edges.get(frame, set()))
        if kids:
            node = parent_node.add(Text(frame, style="bold"), expand=True)
        else:
            node = parent_node.add_leaf(Text(frame, style="cyan"))
        for kid in kids:
            self._add_subtree(node, kid, seen, depth + 1)
