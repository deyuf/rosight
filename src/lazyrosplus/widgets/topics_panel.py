"""Topics panel: list, echo, info, hz, bandwidth."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Input, Static

from lazyrosplus.utils.datatable import (
    current_row_key,
    fit_last_column,
    fit_last_column_when_ready,
    restore_cursor,
)
from lazyrosplus.utils.formatting import format_bytes, format_rate, short_type
from lazyrosplus.widgets.message_tree import MessageTree

if TYPE_CHECKING:
    from lazyrosplus.app import LazyrosPlusApp
    from lazyrosplus.ros.backend import RosBackend, Subscription, TopicInfo

log = logging.getLogger(__name__)


class TopicsPanel(Vertical):
    """Two-column panel: topic table on the left, detail view on the right."""

    BINDINGS = [
        Binding("enter", "echo", "Echo"),
        Binding("i", "info", "Info"),
        Binding("h", "hz", "Hz"),
        Binding("b", "bw", "BW"),
        Binding("space", "toggle_pause", "Pause"),
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

    # ---------------- compose ----------------

    def compose(self) -> ComposeResult:
        with Vertical(id="left"):
            yield Input(placeholder="filter topics…", id="filter")
            yield DataTable(id="topics-table", cursor_type="row", zebra_stripes=True)
        with Vertical(id="right"):
            yield Static("select a topic", id="detail-header")
            yield Static("", id="info-area")
            yield MessageTree(id="msg-tree")

    def on_mount(self) -> None:
        table = self.query_one("#topics-table", DataTable)
        table.add_columns("Topic", "Type", "Pub", "Sub", "Hz", "BW")
        fit_last_column_when_ready(table)
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
    def app_(self) -> LazyrosPlusApp:
        return self.app  # type: ignore[return-value]

    @property
    def ros(self) -> RosBackend | None:
        return getattr(self.app_, "ros", None)

    def _refresh_table(self) -> None:
        # Skip when the tab is hidden — every panel's set_interval keeps
        # firing in the background otherwise, and the 1 s rclpy round-trip
        # adds up across all panels.
        if self.region.width == 0:
            return
        ros = self.ros
        if ros is None or not ros.started:
            return
        try:
            self._topic_cache = ros.list_topics()
        except Exception:
            log.exception("list_topics failed")
            return
        self._render_table()

    def on_show(self) -> None:
        # Refresh immediately on tab switch so the user doesn't have to
        # wait up to a full interval for fresh data.
        self._refresh_table()

    def _render_table(self) -> None:
        table = self.query_one("#topics-table", DataTable)
        # Preserve BOTH axes — `clear()` resets scroll to (0, 0), which made
        # the user's horizontal scroll position jump back every tick.
        scroll = table.scroll_offset
        selected_key = current_row_key(table)
        # One lock-protected call to get every active sub at once, then a
        # dict lookup per row instead of N lock acquisitions.
        subs_by_topic = {s.topic: s for s in self.ros.active_subscriptions()} if self.ros else {}
        table.clear()
        ft = self.filter_text.lower().strip()
        new_idx = -1
        idx = 0
        for ti in self._topic_cache:
            if ft and ft not in ti.name.lower() and ft not in ti.primary_type.lower():
                continue
            sub = subs_by_topic.get(ti.name)
            hz_str = "—"
            bw_str = "—"
            if sub is not None:
                rs = sub.rate.sample()
                bs = sub.bandwidth.sample()
                hz_str = format_rate(rs.hz)
                bw_str = format_bytes(bs.bytes_per_sec) + "/s"
            row_style = "bold" if sub is not None else ""
            table.add_row(
                Text(ti.name, style=row_style),
                Text(short_type(ti.primary_type), style="dim"),
                str(ti.publisher_count),
                str(ti.subscriber_count),
                hz_str,
                bw_str,
                key=ti.name,
            )
            if ti.name == selected_key:
                new_idx = idx
            idx += 1
        restore_cursor(table, selected_key, new_idx)
        try:
            table.scroll_to(x=scroll.x, y=scroll.y, animate=False)
        except Exception:
            pass
        fit_last_column(table)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key is None:
            return
        self.selected_topic = str(event.row_key.value)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # DataTable owns the `enter` keybinding (it's defined in textual's
        # base class with show=False), which means our panel-level
        # `Binding("enter", "echo")` never actually fires — the table
        # consumes the keypress and emits this RowSelected event instead.
        # Translating it back into action_echo restores the original UX:
        # pressing Enter on a row subscribes to that topic.
        if event.row_key is None:
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

    def action_hz(self) -> None:
        # hz info is already shown in the table; ensure subscription so it ticks.
        self.action_echo()

    def action_bw(self) -> None:
        self.action_echo()

    def action_publish(self) -> None:  # pragma: no cover — interactive
        self.app_.notify(
            "publish form not yet implemented in this build",
            severity="warning",
        )

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
            header.update(f"{topic}\n[press enter to subscribe]")
            tree.update_message(None)
            return
        rs = sub.rate.sample()
        bs = sub.bandwidth.sample()
        header.update(
            Text.assemble(
                (f"{topic}\n", "bold cyan"),
                (f"type: {short_type(sub.type_name)}   ", "dim"),
                (f"hz: {format_rate(rs.hz)}   ", "yellow"),
                (f"bw: {format_bytes(bs.bytes_per_sec)}/s   ", "magenta"),
                (f"jitter: {rs.jitter_ms:.1f}ms", "green"),
            )
        )
        if not self.paused and sub.last_msg is not None:
            stamp = (topic, sub.last_msg_ts)
            if stamp != self._tree_ts:
                tree.update_message(sub.last_msg)
                self._tree_ts = stamp

    # ---------------- bridge: forward field selection to plot ----------------

    def on_message_tree_field_selected(
        self,
        event: MessageTree.FieldSelected,  # type: ignore[name-defined]
    ) -> None:
        if not event.is_numeric or not self.selected_topic:
            self.app_.push_status(f"field {event.path} is not numeric — skipped")
            return
        self.app_.add_plot_series(self.selected_topic, event.path)
        self.app_.push_status(f"plot += {self.selected_topic}/{event.path}")
