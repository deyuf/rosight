"""Top-level Textual application.

Holds the :class:`RosBackend`, the panel registry, and the global key
bindings. Each panel is implemented as a self-contained widget under
``rosight.widgets`` and registered here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import Footer, Header, TabbedContent, TabPane

from rosight.config import Config, load_user_state, save_user_state
from rosight.ros.backend import RosBackend, RosUnavailable
from rosight.widgets.actions_panel import ActionsPanel
from rosight.widgets.bags_panel import BagsPanel
from rosight.widgets.command_palette import CommandPalette
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
        )

    # --------------- compose / lifecycle ---------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
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
        if self._owns_ros:
            try:
                self.ros.stop()
            except Exception:
                log.exception("ros stop failed")

    # --------------- actions ---------------

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_command(self) -> None:
        self.push_screen(CommandPalette(), self._on_command_submitted)

    def action_refresh(self) -> None:
        self.push_status("refresh requested")
        # Each panel polls on a timer; nothing else needed.

    def action_tab(self, tab_id: str) -> None:
        try:
            self.query_one(TabbedContent).active = tab_id
        except Exception:
            pass

    # --------------- helpers exposed to panels ---------------

    def push_status(self, msg: str) -> None:
        try:
            bar = self.query_one("#status", StatusBar)
            bar.message = msg
        except Exception:
            log.info(msg)
        log.info("status: %s", msg)

    def add_plot_series(self, topic: str, field_path: str) -> None:
        """Forward field-selected events from the topics panel to plot."""
        try:
            panel = self.query_one(PlotPanel)
            panel.add_series(topic, field_path)
            self.action_tab("plot")
        except Exception:
            log.exception("could not add plot series")

    def add_plot_snapshot_series(self, topic: str, field_path: str) -> None:
        """Forward array-field selection from the topics panel to plot."""
        try:
            panel = self.query_one(PlotPanel)
            panel.add_snapshot_series(topic, field_path)
            self.action_tab("plot")
        except Exception:
            log.exception("could not add plot snapshot series")

    # --------------- background tickers ---------------

    def _refresh_status(self) -> None:
        bar = self.query_one("#status", StatusBar)
        # The status ticker fires on a timer and is independent of test
        # setup/teardown ordering. Tests sometimes swap ``self.ros`` for a
        # minimal stub that mimics only the methods they exercise, so reach
        # for attributes defensively rather than assuming a full RosBackend.
        started = getattr(self.ros, "started", False)
        bar.backend_ok = self.backend_ok and started
        bar.domain_id = getattr(self.ros, "domain_id", None)
        if not started:
            return
        try:
            bar.topics = len(self.ros.list_topics())
            bar.nodes = len(self.ros.list_nodes())
            bar.services = len(self.ros.list_services())
            bar.actions = len(self.ros.list_actions())
            bar.subs = len(self.ros.active_subscriptions())
        except Exception:
            log.debug("status refresh failed", exc_info=True)

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
        }

    def _on_command_submitted(self, raw: str | None) -> None:
        if not raw:
            return
        parts = raw.strip().split()
        cmd, args = parts[0], parts[1:]
        handler = self._commands.get(cmd)
        if handler is None or not handler(args):
            self.push_status(f"unknown command: {raw}")

    # ----- individual command handlers -----

    def _cmd_quit(self, _args: list[str]) -> bool:
        self.exit(0)
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
        self.action_tab("nodes")
        return True

    def _cmd_param(self, args: list[str]) -> bool:
        if not args:
            return False
        self.action_tab("params")
        return True

    def _cmd_plot(self, args: list[str]) -> bool:
        if len(args) < 2:
            return False
        self.add_plot_series(args[0], args[1])
        return True

    def _cmd_plot_array(self, args: list[str]) -> bool:
        if len(args) < 2:
            return False
        self.add_plot_snapshot_series(args[0], args[1])
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
