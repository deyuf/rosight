"""Top-level Textual application.

Holds the :class:`RosBackend`, the panel registry, and the global key
bindings. Each panel is implemented as a self-contained widget under
``rosight.widgets`` and registered here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Input, TabbedContent, TabPane, Tree

from rosight.config import Config, load_user_state, save_user_state
from rosight.ros.backend import RosBackend, RosUnavailable
from rosight.widgets.actions_panel import ActionsPanel
from rosight.widgets.bags_panel import BagsPanel
from rosight.widgets.command_palette import CommandPalette, CommandSuggester
from rosight.widgets.confirm_screen import ConfirmScreen
from rosight.widgets.help_screen import HelpScreen
from rosight.widgets.interfaces_panel import InterfacesPanel
from rosight.widgets.nodes_panel import NodesPanel
from rosight.widgets.params_panel import ParamsPanel
from rosight.widgets.plot_panel import PlotPanel
from rosight.widgets.services_panel import ServicesPanel
from rosight.widgets.status_bar import StatusBar
from rosight.widgets.tf_panel import TfPanel
from rosight.widgets.topics_panel import TopicsPanel

log = logging.getLogger(__name__)

# Commands kept in the palette history (and the state file).
HISTORY_LIMIT = 50


class RosightApp(App[int]):
    """Main Textual application."""

    CSS_PATH = "app.tcss"
    TITLE = "Rosight"
    SUB_TITLE = "ROS 2 TUI"

    BINDINGS = [
        Binding("q,ctrl+c", "quit", "Quit"),
        Binding("?", "help", "Help"),
        Binding(":", "command", "Command"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab('topics')", "Messages", show=False),
        Binding("2", "tab('nodes')", "Nodes", show=False),
        Binding("3", "tab('services')", "Services", show=False),
        Binding("4", "tab('actions')", "Actions", show=False),
        Binding("5", "tab('params')", "Params", show=False),
        Binding("6", "tab('plot')", "Plot", show=False),
        Binding("7", "tab('tf')", "TF", show=False),
        Binding("8", "tab('bags')", "Bags", show=False),
        Binding("9", "tab('interfaces')", "Interfaces", show=False),
        # vim-style motions; active only when ui.vim_keys (see check_action).
        Binding("j", "vim('down')", "Down", show=False),
        Binding("k", "vim('up')", "Up", show=False),
        Binding("g", "vim('top')", "Top", show=False),
        Binding("G", "vim('bottom')", "Bottom", show=False),
    ]

    backend_ok: reactive[bool] = reactive(False)

    def __init__(
        self,
        config: Config | None = None,
        *,
        ros: RosBackend | None = None,
    ) -> None:
        super().__init__()
        self.config: Config = config or Config()
        self._owns_ros = ros is None
        self.ros: RosBackend = ros or RosBackend(
            domain_id=self.config.ros.domain_id,
            default_depth=self.config.ros.queue_depth,
            discovery_period=self.config.ui.discovery_period,
        )
        # Set once we've told the user the executor died, so the 1 Hz status
        # tick doesn't spam notifications.
        self._executor_down_notified = False
        self._cmd_history: list[str] = []
        self._field_cache: dict[tuple[str, bool], list[str]] = {}
        self._ui_state_saved = False

    # --------------- compose / lifecycle ---------------

    def compose(self) -> ComposeResult:
        # ◎ echoes the logo: a reticle locked onto a graph node.
        yield Header(show_clock=True, icon="◎")
        with TabbedContent(initial="topics", id="main-tabs"):
            with TabPane("Messages", id="topics"):
                yield TopicsPanel()
            with TabPane("Nodes", id="nodes"):
                yield NodesPanel()
            with TabPane("Services", id="services"):
                yield ServicesPanel()
            with TabPane("Actions", id="actions"):
                yield ActionsPanel()
            with TabPane("Params", id="params"):
                yield ParamsPanel()
            with TabPane("Plot", id="plot"):
                yield PlotPanel()
            with TabPane("TF", id="tf"):
                yield TfPanel()
            with TabPane("Bags", id="bags"):
                yield BagsPanel()
            with TabPane("Interfaces", id="interfaces"):
                yield InterfacesPanel()
        with Vertical(id="bottom-bar"):
            yield StatusBar(id="status")
            yield Footer()

    async def on_mount(self) -> None:
        # Restore the theme the user last picked via Ctrl+P → Change theme.
        # Failures are silent: if the state file is missing or names a theme
        # Textual no longer ships, we just stay on the default.
        try:
            state = load_user_state()
            saved = state.get("theme")
            if isinstance(saved, str) and self.get_theme(saved) is not None:
                self.theme = saved
        except Exception:
            log.debug("could not restore theme", exc_info=True)

        # Persist on every subsequent theme change.
        try:
            self.theme_changed_signal.subscribe(self, self._on_theme_changed)
        except Exception:
            log.debug("could not subscribe to theme_changed_signal", exc_info=True)

        # Try to start the ROS backend; downgrade to a banner on failure.
        if self._owns_ros:
            try:
                self.ros.start()
                self.backend_ok = True
            except RosUnavailable as e:
                self.backend_ok = False
                self.notify(str(e), title="ROS 2 unavailable", severity="warning", timeout=10)
            except Exception:
                log.exception("ROS backend failed to start")
                self.backend_ok = False
                self.notify(
                    "ROS backend failed to start — see logs.",
                    title="error",
                    severity="error",
                )
        else:
            self.backend_ok = self.ros.started

        self.set_interval(self.config.ui.discovery_period, self._refresh_status)
        try:
            self._restore_ui_state(load_user_state())
        except Exception:
            log.debug("could not restore UI state", exc_info=True)

    def _on_theme_changed(self, theme) -> None:
        """Persist the chosen theme so it survives restarts."""
        try:
            name = getattr(theme, "name", None) or self.theme
            if not isinstance(name, str):
                return
            state = load_user_state()
            state["theme"] = name
            save_user_state(state)
        except Exception:
            log.debug("could not persist theme", exc_info=True)

    async def on_unmount(self) -> None:
        if not self._ui_state_saved:
            self._save_ui_state()
        if self._owns_ros:
            try:
                self.ros.stop()
            except Exception:
                log.exception("ros stop failed")

    # --------------- actions ---------------

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        # With vim_keys off, report the motion bindings as unavailable so the
        # key falls through to whatever else handles it.
        return action != "vim" or self.config.ui.vim_keys

    def action_vim(self, motion: str) -> None:
        """Map j/k/g/G onto the focused table or tree."""
        w = self.focused
        if w is None:
            return
        if motion == "down" and hasattr(w, "action_cursor_down"):
            w.action_cursor_down()
        elif motion == "up" and hasattr(w, "action_cursor_up"):
            w.action_cursor_up()
        elif isinstance(w, DataTable) and w.row_count:
            w.move_cursor(row=0 if motion == "top" else w.row_count - 1, animate=False)
        elif isinstance(w, Tree):
            w.cursor_line = 0 if motion == "top" else w.last_line

    async def action_quit(self) -> None:
        """Quit, but confirm first while a bag is recording or playing."""
        try:
            running = self.query_one(BagsPanel).running_processes()
        except Exception:
            running = []
        if not running:
            self._save_ui_state()
            self.exit(0)
            return
        what = " and ".join(running)
        question = (
            f"A bag {what} is still running.\n"
            "Quitting stops it (the bag is finalized first).\n\n"
            "Quit anyway?"
        )

        def _done(yes: bool | None) -> None:
            if yes:
                self._save_ui_state()
                self.exit(0)

        self.push_screen(ConfirmScreen(question), _done)

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_command(self) -> None:
        suggester = CommandSuggester(list(self._commands), self._known_topics, self._plot_fields)
        self.push_screen(
            CommandPalette(history=self._cmd_history, suggester=suggester),
            self._on_command_submitted,
        )

    # ----- completion providers for the command palette -----

    def _known_topics(self) -> list[str]:
        try:
            snap_fn = getattr(self.ros, "graph_snapshot", None)
            topics = snap_fn().topics if callable(snap_fn) else self.ros.list_topics()
            return [t.name for t in topics]
        except Exception:
            return []

    def _plot_fields(self, topic: str, arrays: bool) -> list[str]:
        """Plottable field paths of ``topic``'s message type (cached per type)."""
        from rosight.ros.introspection import get_message_class, iter_fields

        try:
            snap_fn = getattr(self.ros, "graph_snapshot", None)
            topics = snap_fn().topics if callable(snap_fn) else self.ros.list_topics()
            type_name = next(t.primary_type for t in topics if t.name == topic)
        except Exception:
            return []
        key = (type_name, arrays)
        if key not in self._field_cache:
            try:
                msg = get_message_class(type_name)()
                self._field_cache[key] = [
                    e.path
                    for e in iter_fields(msg)
                    if (e.is_array_numeric if arrays else e.is_numeric)
                ]
            except Exception:
                self._field_cache[key] = []
        return self._field_cache[key]

    # ----- UI state persisted across restarts -----

    def _filter_panels(self) -> dict[str, Any]:
        return {
            "topics": self.query_one(TopicsPanel),
            "nodes": self.query_one(NodesPanel),
            "services": self.query_one(ServicesPanel),
            "actions": self.query_one(ActionsPanel),
            "params": self.query_one(ParamsPanel),
        }

    def _collect_ui_state(self) -> dict[str, object]:
        return {
            "last_tab": self.query_one(TabbedContent).active,
            "plot_series": self.query_one(PlotPanel).sources_spec(),
            "command_history": self._cmd_history[-HISTORY_LIMIT:],
            "filters": {name: p.filter_text for name, p in self._filter_panels().items()},
        }

    def _save_ui_state(self) -> None:
        try:
            state = load_user_state()
            state.update(self._collect_ui_state())
            save_user_state(state)
            self._ui_state_saved = True
        except Exception:
            log.debug("could not save UI state", exc_info=True)

    def _restore_ui_state(self, state: dict) -> None:
        history = state.get("command_history")
        if isinstance(history, list):
            self._cmd_history = [str(h) for h in history][-HISTORY_LIMIT:]
        filters = state.get("filters")
        if isinstance(filters, dict):
            panels = self._filter_panels()
            for name, value in filters.items():
                panel = panels.get(name)
                if panel is None or not isinstance(value, str) or not value:
                    continue
                panel.filter_text = value
                try:
                    panel.query_one("#filter", Input).value = value
                except Exception:
                    pass
        series = state.get("plot_series")
        if isinstance(series, list) and series:
            # Subscriptions are retried by the plot until topics are discovered.
            self.query_one(PlotPanel).restore_sources([str(s) for s in series])
        tab = state.get("last_tab")
        if isinstance(tab, str) and tab:
            self.action_tab(tab)

    def action_refresh(self) -> None:
        self.push_status("refresh requested")
        # Wake the background graph monitor; panels pick the new snapshot
        # up on their next tick.
        request = getattr(self.ros, "request_graph_refresh", None)
        if callable(request):
            request()

    def action_tab(self, tab_id: str) -> None:
        try:
            tabs = self.query_one(TabbedContent)
        except Exception:
            return
        if tabs.active != tab_id:
            # A widget that keeps focus inside the pane being hidden makes
            # Textual move focus to a sibling in that same pane, and
            # TabbedContent then re-activates it — pressing 1-9 with a table
            # focused bounced straight back. Drop focus first.
            self.screen.set_focus(None)
        tabs.active = tab_id
        self.call_after_refresh(self._focus_pane, tab_id)

    def _focus_pane(self, tab_id: str) -> None:
        """Focus the main table/tree of the visible pane so keys work at once."""
        if self.focused is not None:
            return  # something (e.g. a goto) already chose a target
        try:
            pane = self.query_one(f"TabPane#{tab_id}")
        except Exception:
            return
        for widget in pane.query("DataTable, Tree"):
            if widget.focusable and widget.display:
                widget.focus()
                return

    # --------------- helpers exposed to panels ---------------

    def push_status(self, msg: str) -> None:
        try:
            bar = self.query_one("#status", StatusBar)
            bar.message = msg
        except Exception:
            log.info(msg)
        log.info("status: %s", msg)

    def add_plot_series(self, topic: str, field_path: str, *, switch: bool = False) -> None:
        """Add a scalar field to the plot.

        From the message tree we stay on the current tab (``switch=False``)
        so several fields can be added in a row; the status bar confirms
        each one. The ``:plot`` command jumps to the plot.
        """
        try:
            self.query_one(PlotPanel).add_series(topic, field_path)
            if switch:
                self.action_tab("plot")
        except Exception:
            log.exception("could not add plot series")

    def add_plot_snapshot_series(
        self, topic: str, field_path: str, *, switch: bool = False
    ) -> None:
        """Add a numeric-array field as a snapshot series (see add_plot_series)."""
        try:
            self.query_one(PlotPanel).add_snapshot_series(topic, field_path)
            if switch:
                self.action_tab("plot")
        except Exception:
            log.exception("could not add plot snapshot series")

    # ----- cross-panel navigation (used by the Nodes endpoint tree) -----

    def goto_topic(self, topic: str) -> None:
        self.action_tab("topics")
        # Tab switch lays the panel out on the next refresh.
        self.call_after_refresh(self._goto, TopicsPanel, "focus_topic", topic)

    def goto_node(self, fqn: str) -> None:
        self.action_tab("nodes")
        self.call_after_refresh(self._goto, NodesPanel, "focus_item", fqn)

    def goto_service(self, name: str) -> None:
        self.action_tab("services")
        self.call_after_refresh(self._goto, ServicesPanel, "focus_item", name)

    def goto_action(self, name: str) -> None:
        self.action_tab("actions")
        self.call_after_refresh(self._goto, ActionsPanel, "focus_item", name)

    def _goto(self, panel_cls: type, method: str, key: str) -> None:
        try:
            found = getattr(self.query_one(panel_cls), method)(key)
        except Exception:
            log.debug("goto %s failed", key, exc_info=True)
            found = False
        if not found:
            self.push_status(f"{key} is not in the list (not discovered yet?)")

    def export_path(self, filename: str) -> Path:
        """Absolute path for an exported file, honouring ``ui.export_dir``.

        Creates the directory if needed; falls back to cwd if it can't.
        """
        base = self.config.ui.export_dir
        root = Path(base).expanduser() if base else Path.cwd()
        try:
            root.mkdir(parents=True, exist_ok=True)
        except OSError:
            log.warning("export_dir %s not writable, using cwd", root)
            root = Path.cwd()
        return (root / filename).resolve()

    def unsubscribe_topic(self, topic: str) -> bool:
        """Drop a subscription; warn if plot series depend on it."""
        ros = self.ros
        if ros is None or ros.get_subscription(topic) is None:
            return False
        ros.unsubscribe(topic)
        users = 0
        try:
            plot = self.query_one(PlotPanel)
            users = plot.series_using(topic)
            plot.mark_unsubscribed(topic)
        except Exception:
            pass
        suffix = f" — {users} plot series paused" if users else ""
        self.push_status(f"unsubscribed {topic}{suffix}")
        return True

    # --------------- background tickers ---------------

    def _refresh_status(self) -> None:
        # The interval timer can still fire while the app is tearing down
        # its screen, after the status bar has been removed.
        try:
            bar = self.query_one("#status", StatusBar)
        except NoMatches:
            return
        # The status ticker fires on a timer and is independent of test
        # setup/teardown ordering. Tests sometimes swap ``self.ros`` for a
        # minimal stub that mimics only the methods they exercise, so reach
        # for attributes defensively rather than assuming a full RosBackend.
        ros = self.ros
        started = getattr(ros, "started", False)
        alive = getattr(ros, "executor_alive", True) if started else False
        bar.backend_ok = self.backend_ok and started and alive
        bar.domain_id = getattr(ros, "domain_id", None)
        if started and not alive:
            self._on_executor_down()
        elif alive:
            self._executor_down_notified = False
        if not started:
            return
        try:
            snap_fn = getattr(ros, "graph_snapshot", None)
            if callable(snap_fn):
                # O(1): read the background monitor's snapshot instead of
                # four synchronous graph queries per second.
                snap = snap_fn()
                topics, nodes, services, actions = snap.content()
            else:
                topics, nodes = ros.list_topics(), ros.list_nodes()
                services, actions = ros.list_services(), ros.list_actions()
            bar.topics, bar.nodes = len(topics), len(nodes)
            bar.services, bar.actions = len(services), len(actions)
            bar.subs = len(ros.active_subscriptions())
        except Exception:
            log.debug("status refresh failed", exc_info=True)

    def _on_executor_down(self) -> None:
        """The rclpy spin thread died: nothing will be received any more."""
        err = getattr(self.ros, "last_error", None)
        self.push_status("ROS executor stopped — run :reconnect")
        if self._executor_down_notified:
            return
        self._executor_down_notified = True
        detail = f"\n{err}" if err else ""
        self.notify(
            f"The ROS executor thread stopped; topics will not update.{detail}\n"
            "Run :reconnect to restart the backend.",
            title="ROS executor stopped",
            severity="error",
            timeout=15,
        )

    # --------------- command palette ---------------

    # Command dispatch table. Each handler receives the parsed args list
    # and returns ``True`` if it consumed the command (so we don't fall
    # back to the "unknown command" warning), ``False`` to reject — typ.
    # because the required arg count wasn't met. Kept as a property so
    # the bound methods see ``self``.
    @property
    def _commands(self) -> dict[str, Callable[[list[str]], bool]]:
        return {
            "q": self._cmd_quit,
            "quit": self._cmd_quit,
            "exit": self._cmd_quit,
            "topic": self._cmd_topic,
            "node": self._cmd_node,
            "param": self._cmd_param,
            "plot": self._cmd_plot,
            "plot-array": self._cmd_plot_array,
            "view": self._cmd_view,
            "record": self._cmd_record,
            "help": self._cmd_help,
            "domain": self._cmd_domain,
            "reconnect": self._cmd_reconnect,
            "unsub": self._cmd_unsub,
        }

    def _on_command_submitted(self, raw: str | None) -> None:
        if not raw:
            return
        raw = raw.strip()
        if not self._cmd_history or self._cmd_history[-1] != raw:
            self._cmd_history.append(raw)
            del self._cmd_history[:-HISTORY_LIMIT]
        parts = raw.split()
        cmd, args = parts[0], parts[1:]
        handler = self._commands.get(cmd)
        if handler is None or not handler(args):
            self.push_status(f"unknown command: {raw}")

    # ----- individual command handlers -----

    def _cmd_quit(self, _args: list[str]) -> bool:
        self.run_worker(self.action_quit(), group="rosight-quit")
        return True

    def _cmd_topic(self, args: list[str]) -> bool:
        if not args:
            return False
        self.action_tab("topics")
        try:
            tp = self.query_one(TopicsPanel)
            tp.filter_text = args[0]
        except Exception:
            pass
        return True

    def _cmd_node(self, args: list[str]) -> bool:
        if not args:
            return False
        self.goto_node(_as_fqn(args[0]))
        return True

    def _cmd_param(self, args: list[str]) -> bool:
        if not args:
            return False
        fqn = _as_fqn(args[0])
        self.action_tab("params")
        self.call_after_refresh(self._goto, ParamsPanel, "open_node", fqn)
        return True

    def _cmd_plot(self, args: list[str]) -> bool:
        if len(args) < 2:
            return False
        self.add_plot_series(args[0], args[1], switch=True)
        return True

    def _cmd_plot_array(self, args: list[str]) -> bool:
        if len(args) < 2:
            return False
        self.add_plot_snapshot_series(args[0], args[1], switch=True)
        return True

    def _cmd_view(self, args: list[str]) -> bool:
        if not args:
            return False
        try:
            tp = self.query_one(TopicsPanel)
            tp.selected_topic = args[0]
            tp.action_view_image()
        except Exception:
            self.push_status(f"could not open image view for {args[0]}")
        return True

    def _cmd_record(self, _args: list[str]) -> bool:
        self.action_tab("bags")
        return True

    def _cmd_help(self, _args: list[str]) -> bool:
        self.action_help()
        return True

    def _cmd_unsub(self, args: list[str]) -> bool:
        if not args:
            return False
        ros = self.ros
        if args[0] == "all":
            topics = [s.topic for s in ros.active_subscriptions()] if ros else []
        else:
            topics = [args[0]]
        done = [t for t in topics if self.unsubscribe_topic(t)]
        if args[0] == "all":
            self.push_status(f"unsubscribed {len(done)} topic(s)")
        elif not done:
            self.push_status(f"not subscribed: {args[0]}")
        return True

    def _cmd_reconnect(self, _args: list[str]) -> bool:
        self.push_status("reconnecting…")
        self.run_worker(self._apply_reconnect(), group="rosight-domain", exclusive=True)
        return True

    async def _apply_reconnect(self) -> None:
        try:
            await asyncio.to_thread(self.ros.restart)
            self.backend_ok = self.ros.started
            self._executor_down_notified = False
            self.notify("ROS backend restarted\n(subscriptions cleared)", title="Reconnect")
        except RosUnavailable as e:
            self.backend_ok = False
            self.notify(str(e), title="ROS 2 unavailable", severity="warning")
        except Exception as e:
            log.exception("reconnect failed")
            self.notify(f"reconnect failed: {e}", severity="error")

    def _cmd_domain(self, args: list[str]) -> bool:
        if not args:
            return False
        self._switch_domain(args[0])
        return True

    def _switch_domain(self, raw_id: str) -> None:
        """Validate the request and hand the blocking restart to a worker.

        Validation (parse + range check) runs synchronously so the user
        sees the "invalid"/"out of range" warning immediately. The actual
        rclpy teardown + init goes to :meth:`_apply_domain` running on a
        worker thread — it can take 100s of ms and would otherwise freeze
        the Textual loop. Any subscriptions are lost — panels rediscover.
        """
        try:
            new_id = int(raw_id)
        except ValueError:
            self.notify(f"invalid domain id: {raw_id!r}", severity="warning", title="Domain")
            return
        if not 0 <= new_id <= 232:  # ROS_DOMAIN_ID range
            self.notify(
                f"domain id {new_id} outside valid range 0..232",
                severity="warning",
                title="Domain",
            )
            return
        self.push_status(f"switching to DOMAIN_ID={new_id}…")
        self.run_worker(self._apply_domain(new_id), group="rosight-domain", exclusive=True)

    async def _apply_domain(self, new_id: int) -> None:
        try:
            await asyncio.to_thread(self.ros.set_domain_id, new_id)
            self.backend_ok = self.ros.started
            self.notify(
                f"now on ROS_DOMAIN_ID={new_id}\n(subscriptions cleared)",
                title="Domain",
            )
        except RosUnavailable as e:
            self.backend_ok = False
            self.notify(str(e), title="ROS 2 unavailable", severity="warning")
        except Exception as e:
            log.exception("set_domain_id failed")
            self.notify(f"failed to switch domain: {e}", severity="error")


def _as_fqn(name: str) -> str:
    """``talker`` → ``/talker``; fully qualified names pass through."""
    return name if name.startswith("/") else f"/{name}"
