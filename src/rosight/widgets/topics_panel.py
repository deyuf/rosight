"""Topics panel: list, echo, info, hz, bandwidth."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input, Static

from rosight.utils.datatable import fit_last_column, fit_last_column_when_ready, sync_table
from rosight.utils.formatting import format_bytes, format_rate, short_type, sparkline
from rosight.utils.fuzzy import matches
from rosight.widgets._base import (
    PLACEHOLDER_KEY,
    empty_state_text,
    fetch_graph_items,
    placeholder_row,
)
from rosight.widgets.message_tree import MessageTree

# Seconds of Hz history shown in the Trend column (one sample per refresh).
_TREND_LEN = 12
_COLUMNS = ("Topic", "Type", "Pub", "Sub", "Hz", "Trend", "BW")

if TYPE_CHECKING:
    from rosight.app import RosightApp
    from rosight.ros.backend import RosBackend, Subscription, TopicInfo

log = logging.getLogger(__name__)


class TopicsPanel(Vertical):
    """Two-column panel: topic table on the left, detail view on the right."""

    BINDINGS = [
        Binding("enter", "echo", "Echo"),
        Binding("x", "unsubscribe", "Unsub"),
        Binding("i", "info", "Info"),
        Binding("v", "view_image", "View image"),
        Binding("space", "toggle_pause", "Pause"),
        Binding("left_square_bracket", "history(1)", "Older", show=False),
        Binding("right_square_bracket", "history(-1)", "Newer", show=False),
        Binding("escape", "close_search", "Close search", show=False),
        Binding("P", "publish", "Publish"),
        Binding("/", "filter", "Filter"),
    ]

    DEFAULT_CSS = """
    TopicsPanel { layout: horizontal; overflow: hidden; }
    TopicsPanel > #left {
        width: 45%; min-width: 40;
        border-right: solid $primary 30%;
        overflow: hidden;
    }
    TopicsPanel > #right { width: 1fr; overflow: hidden; }
    TopicsPanel #filter { dock: top; height: 3; }
    TopicsPanel DataTable { height: 1fr; }
    TopicsPanel #detail-header {
        background: $boost;
        color: $text;
        padding: 0 1;
        height: auto;
    }
    TopicsPanel #info-area {
        background: $surface;
        color: $text;
        padding: 0 1;
        height: auto;
        max-height: 10;
    }
    TopicsPanel MessageTree { height: 1fr; }
    TopicsPanel #tree-search { display: none; height: 3; }
    TopicsPanel #tree-search.-visible { display: block; }
    """

    filter_text: reactive[str] = reactive("")
    paused: reactive[bool] = reactive(False)
    selected_topic: reactive[str | None] = reactive(None)

    def __init__(self) -> None:
        super().__init__()
        self._topic_cache: list[TopicInfo] = []
        # (selected_topic, last_msg_ts) of the message currently in the tree;
        # used to skip the O(fields) rebuild when nothing changed.
        self._tree_ts: tuple[str | None, float] = (None, 0.0)
        self._graph_gen: int | None = None
        self._hz_hist: dict[str, deque[float]] = {}
        # Echo history frozen at pause time: (topic, entries); index 0 = newest.
        self._frozen: tuple[str, list] | None = None
        self._hist_idx = 0

    # ---------------- compose ----------------

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Input(placeholder="filter topics… (fuzzy)", id="filter")
            yield DataTable(id="topics-table", cursor_type="row", zebra_stripes=True)
        with Vertical(id="right"):
            yield Static("select a topic", id="detail-header")
            yield Static("", id="info-area")
            yield Input(
                placeholder="search fields…  enter: find · n/N: next/prev", id="tree-search"
            )
            yield MessageTree(id="msg-tree")

    def on_mount(self) -> None:
        table = self.query_one("#topics-table", DataTable)
        table.add_columns(*_COLUMNS)
        fit_last_column_when_ready(table)
        self._render_table()
        self._refresh_table()
        self.set_interval(1.0, self._refresh_table)
        self.set_interval(0.25, self._refresh_detail)

    def on_resize(self) -> None:
        fit_last_column_when_ready(self.query_one("#topics-table", DataTable))

    # ---------------- filter ----------------

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter":
            self.filter_text = event.value
            self._render_table()

    def action_filter(self) -> None:
        self.query_one("#filter", Input).focus()

    # ---------------- table ----------------

    @property
    def app_(self) -> RosightApp:
        return self.app  # type: ignore[return-value]

    @property
    def ros(self) -> RosBackend | None:
        return getattr(self.app_, "ros", None)

    def _refresh_table(self) -> None:
        # Skip when the tab is hidden — timers keep firing in the background.
        if self.region.width == 0:
            return
        ros = self.ros
        if ros is None or not ros.started:
            return
        try:
            self._topic_cache, self._graph_gen = fetch_graph_items(ros, "topics", "list_topics")
        except Exception:
            log.exception("list_topics failed")
            return
        self._sample_trends()
        self._render_table()

    def on_show(self) -> None:
        # Refresh immediately on tab switch so the user doesn't have to
        # wait up to a full interval for fresh data.
        self._refresh_table()

    def _subs_by_topic(self) -> dict[str, Subscription]:
        ros = self.ros
        if ros is None:
            return {}
        try:
            return {s.topic: s for s in ros.active_subscriptions()}
        except Exception:
            return {}

    def _sample_trends(self) -> None:
        """Append one Hz sample per subscribed topic (called at 1 Hz)."""
        subs = self._subs_by_topic()
        for topic in list(self._hz_hist):
            if topic not in subs:
                del self._hz_hist[topic]
        for topic, sub in subs.items():
            hist = self._hz_hist.setdefault(topic, deque(maxlen=_TREND_LEN))
            hist.append(sub.rate.sample().hz)

    def _row_cells(self, ti: TopicInfo, sub: Subscription | None) -> tuple:
        hz_cell: Text | str = "—"
        bw_str = "—"
        trend = ""
        if sub is not None:
            hz = sub.rate.sample().hz
            if sub.qos_incompatible and hz == 0:
                hz_cell = Text("QoS!", style="bold red")
            else:
                hz_cell = format_rate(hz)
            bw_str = format_bytes(sub.bandwidth.sample().bytes_per_sec) + "/s"
            trend = sparkline(tuple(self._hz_hist.get(ti.name, ())))
        name = Text()
        if sub is not None:
            name.append("● ", style="bold green")
            name.append(ti.name, style="bold")
        else:
            name.append("  " + ti.name)
        return (
            name,
            Text(short_type(ti.primary_type), style="dim"),
            str(ti.publisher_count),
            str(ti.subscriber_count),
            hz_cell,
            Text(trend, style="green"),
            bw_str,
        )

    def _render_table(self) -> None:
        table = self.query_one("#topics-table", DataTable)
        # One lock-protected call for every active sub, then a dict lookup
        # per row instead of N lock acquisitions.
        subs = self._subs_by_topic()
        rows = [
            (ti.name, self._row_cells(ti, subs.get(ti.name)))
            for ti in self._topic_cache
            if matches(self.filter_text, ti.name, ti.primary_type)
        ]
        if not rows:
            text = empty_state_text(self.ros, self._graph_gen, self.filter_text, "topics")
            rows = [placeholder_row(text, len(_COLUMNS))]
        # Incremental: on a normal tick only the Hz/Trend/BW cells change,
        # so cursor and scroll stay put and nothing flickers.
        if sync_table(table, rows):
            fit_last_column(table)

    def focus_topic(self, topic: str) -> bool:
        """Clear the filter, move the cursor to ``topic`` and focus the table."""
        self.filter_text = ""
        self.query_one("#filter", Input).value = ""
        self._refresh_table()
        self._render_table()
        table = self.query_one("#topics-table", DataTable)
        keys = [str(r.key.value) for r in table.ordered_rows]
        if topic not in keys:
            return False
        table.move_cursor(row=keys.index(topic), animate=False)
        self.selected_topic = topic
        table.focus()
        return True

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None or str(event.row_key.value) == PLACEHOLDER_KEY:
            return
        self.selected_topic = str(event.row_key.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # DataTable owns the `enter` keybinding (it's defined in textual's
        # base class with show=False), which means our panel-level
        # `Binding("enter", "echo")` never actually fires — the table
        # consumes the keypress and emits this RowSelected event instead.
        # Translating it back into action_echo restores the original UX:
        # pressing Enter on a row subscribes to that topic.
        if event.row_key is None or str(event.row_key.value) == PLACEHOLDER_KEY:
            return
        self.selected_topic = str(event.row_key.value)
        self.action_echo()
        # Auto-focus the message tree so the user can immediately expand
        # fields with arrow keys / space, without an extra Tab.
        try:
            self.query_one("#msg-tree").focus()
        except Exception:
            pass

    # ---------------- echo / detail ----------------

    def action_echo(self) -> None:
        topic = self.selected_topic
        if not topic or not self.ros:
            return
        ti = next((t for t in self._topic_cache if t.name == topic), None)
        if ti is None or not ti.types:
            self.app_.notify(f"no type for {topic!r}", severity="warning")
            return
        if self.ros.get_subscription(topic) is not None:
            self.app_.notify(f"already subscribed: {topic}", title="Subscribe")
            return
        try:
            self.ros.subscribe(topic, ti.primary_type)
            self.app_.notify(
                f"subscribed: {topic}\ntype: {ti.primary_type}",
                title="Subscribe",
            )
        except Exception as e:
            log.exception("subscribe failed")
            self.app_.notify(f"subscribe failed: {e}", severity="error")

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        self._frozen = None
        self._hist_idx = 0
        if self.paused:
            self._freeze_history()
        else:
            self._tree_ts = (None, 0.0)  # force the live message back in
        self._refresh_detail()

    def _freeze_history(self) -> None:
        topic = self.selected_topic
        sub = self.ros.get_subscription(topic) if topic and self.ros else None
        self._frozen = (topic, sub.history()) if sub is not None and topic else None

    def action_history(self, step: int) -> None:
        """While paused, step through the last messages ([ older, ] newer)."""
        if not self.paused:
            self.app_.push_status("pause first (space) to step through message history")
            return
        if self._frozen is None or self._frozen[0] != self.selected_topic:
            self._freeze_history()
            self._hist_idx = 0
        if self._frozen is None or not self._frozen[1]:
            self.app_.push_status("no message history for this topic yet")
            return
        last = len(self._frozen[1]) - 1
        self._hist_idx = max(0, min(last, self._hist_idx + step))
        self._show_history_entry()

    def _show_history_entry(self) -> None:
        if self._frozen is None or self.ros is None:
            return
        topic, entries = self._frozen
        sub = self.ros.get_subscription(topic)
        if sub is None or not entries:
            return
        msg = sub.decode_entry(entries[-1 - self._hist_idx])
        self.query_one("#msg-tree", MessageTree).update_message(msg)
        self._refresh_detail()

    def _history_caption(self) -> str:
        if not self.paused:
            return ""
        if self._frozen is None or not self._frozen[1]:
            return "⏸ paused"
        entries = self._frozen[1]
        idx = self._hist_idx
        age = entries[-1][1] - entries[-1 - idx][1]
        pos = f"{len(entries) - idx}/{len(entries)}"
        return f"⏸ paused · message {pos} ({age:+.2f}s from newest) · [ older  ] newer"

    # ---------------- field search ----------------

    def on_message_tree_search_requested(self, _event: MessageTree.SearchRequested) -> None:
        box = self.query_one("#tree-search", Input)
        box.add_class("-visible")
        box.focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "tree-search":
            return
        tree = self.query_one("#msg-tree", MessageTree)
        if not tree.search(event.value):
            self.app_.notify(f"no field matches {event.value!r}", severity="warning")
        self.action_close_search()

    def action_close_search(self) -> None:
        box = self.query_one("#tree-search", Input)
        if box.has_class("-visible"):
            box.remove_class("-visible")
            self.query_one("#msg-tree", MessageTree).focus()

    def action_info(self) -> None:
        topic = self.selected_topic
        if not topic or not self.ros:
            return
        info_lines = [f"Topic: {topic}"]
        ti = next((t for t in self._topic_cache if t.name == topic), None)
        if ti:
            info_lines.append(f"Types: {', '.join(ti.types)}")
            info_lines.append(f"Publishers: {ti.publisher_count}")
            info_lines.append(f"Subscribers: {ti.subscriber_count}")
        try:
            specs = self.ros.publisher_qos(topic)
            for i, s in enumerate(specs):
                info_lines.append(
                    f"  pub[{i}] reliability={s.reliability.value} "
                    f"durability={s.durability.value} depth={s.depth}"
                )
        except Exception:
            pass
        text = "\n".join(info_lines)
        # Use a separate static so the realtime hz/bw refresh in
        # `_refresh_detail` doesn't clobber it.
        self.query_one("#info-area", Static).update(text)

    def action_unsubscribe(self) -> None:
        """Stop receiving the selected topic (frees bandwidth and CPU)."""
        topic = self.selected_topic
        if not topic:
            return
        unsub = getattr(self.app_, "unsubscribe_topic", None)
        if not callable(unsub) or not unsub(topic):
            self.app_.push_status(f"not subscribed: {topic}")
            return
        self._tree_ts = (None, 0.0)
        self._render_table()
        self._refresh_detail()

    def action_publish(self) -> None:
        """Open a YAML form for the selected topic and publish it once.

        Pre-filled with the last received message when subscribed, else the
        type's default values.
        """
        from rosight.ros.introspection import get_message_class
        from rosight.ros.yaml_msg import MessageYamlError, message_to_yaml, yaml_to_message
        from rosight.widgets.yaml_form import YamlFormScreen

        topic = self.selected_topic
        ros = self.ros
        if not topic:
            self.app_.push_status("select a topic to publish to")
            return
        if ros is None or not ros.started:
            self.app_.notify("cannot publish: ROS backend not running", severity="warning")
            return
        ti = next((t for t in self._topic_cache if t.name == topic), None)
        if ti is None or not ti.types:
            self.app_.notify(f"no type for {topic!r}", severity="warning")
            return
        type_name = ti.primary_type
        try:
            msg_cls = get_message_class(type_name)
        except Exception as e:
            self.app_.notify(f"cannot load {type_name}: {e}", severity="error")
            return
        sub = ros.get_subscription(topic)
        template = sub.snapshot()[0] if sub is not None else None
        text = message_to_yaml(template if template is not None else msg_cls())

        def validate(t: str) -> str | None:
            try:
                yaml_to_message(t, msg_cls)
            except MessageYamlError as e:
                return str(e)
            return None

        def done(t: str | None) -> None:
            if t is not None:
                msg = yaml_to_message(t, msg_cls)
                self.run_worker(self._publish(topic, type_name, msg), group="publish")

        self.app_.push_screen(
            YamlFormScreen(
                f"Publish to {topic}  [{short_type(type_name)}]",
                text,
                hint="published once",
                submit_label="Publish",
                validate=validate,
            ),
            done,
        )

    async def _publish(self, topic: str, type_name: str, msg: object) -> None:
        ros = self.ros
        if ros is None:
            return
        try:
            await asyncio.to_thread(ros.publish_once, topic, type_name, msg)
        except Exception as e:
            log.exception("publish failed")
            self.app_.notify(f"publish failed: {e}", severity="error")
            return
        self.app_.notify(f"published to {topic}", title="Publish")

    def action_view_image(self) -> None:
        """Open a modal image preview if the selected topic is an image type."""
        from rosight.widgets.image_screen import IMAGE_TYPES, ImagePreviewScreen

        topic = self.selected_topic
        ros = self.ros
        if not topic:
            self.app_.push_status("select a topic first")
            return
        if ros is None or not ros.started:
            self.app_.push_status("ROS not connected — cannot view image")
            return
        ti = next((t for t in self._topic_cache if t.name == topic), None)
        if ti is None or not ti.types:
            self.app_.notify(f"no type for {topic!r}", severity="warning")
            return
        type_name = ti.primary_type
        if type_name not in IMAGE_TYPES:
            self.app_.push_status(f"{topic} is {type_name}, not an image topic")
            return
        self.app_.push_screen(ImagePreviewScreen(ros, topic, type_name))

    def _refresh_detail(self) -> None:
        # 4 Hz timer — silently no-op when the tab is hidden so we don't
        # burn CPU walking the message tree for a panel nobody is looking at.
        if self.region.width == 0:
            return
        topic = self.selected_topic
        ros = self.ros
        if not topic or ros is None:
            return
        sub: Subscription | None = ros.get_subscription(topic)
        header = self.query_one("#detail-header", Static)
        tree = self.query_one("#msg-tree", MessageTree)
        if sub is None:
            # Text, not a markup string: "[press enter…]" would be parsed
            # as a Rich markup tag.
            header.update(
                Text.assemble((f"{topic}\n", "bold cyan"), ("enter: subscribe", "dim italic"))
            )
            tree.update_message(None)
            return
        rs = sub.rate.sample()
        bs = sub.bandwidth.sample()
        text = Text.assemble(
            (f"{topic}\n", "bold cyan"),
            (f"type: {short_type(sub.type_name)}   ", "dim"),
            (f"hz: {format_rate(rs.hz)}   ", "yellow"),
            (f"bw: {format_bytes(bs.bytes_per_sec)}/s   ", "magenta"),
            (f"jitter: {rs.jitter_ms:.1f}ms", "green"),
        )
        if sub.qos_incompatible:
            text.append(
                f"\n⚠ incompatible QoS with publisher: {sub.qos_incompatible.lower()}"
                f" ({sub.qos_incompatible_count}x) — press i for publisher QoS",
                style="bold red",
            )
        if sub.decode_errors:
            text.append(f"\n⚠ {sub.decode_errors} message(s) failed to decode", style="red")
        caption = self._history_caption()
        if caption:
            text.append(f"\n{caption}", style="bold yellow")
        header.update(text)
        if not self.paused:
            msg, ts = sub.snapshot()
            if msg is not None:
                stamp = (topic, ts)
                if stamp != self._tree_ts:
                    tree.update_message(msg)
                    self._tree_ts = stamp

    # ---------------- bridge: forward field selection to plot ----------------

    def on_message_tree_field_selected(
        self,
        event: MessageTree.FieldSelected,  # type: ignore[name-defined]
    ) -> None:
        if not self.selected_topic:
            return
        if event.kind == "array":
            self.app_.add_plot_snapshot_series(self.selected_topic, event.path)
            self.app_.push_status(f"plot (snap) += {self.selected_topic}/{event.path}")
            return
        if not event.is_numeric:
            self.app_.push_status(f"field {event.path} is not numeric — skipped")
            return
        self.app_.add_plot_series(self.selected_topic, event.path)
        self.app_.push_status(f"plot += {self.selected_topic}/{event.path}")
