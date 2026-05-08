"""Top-level Textual application.

Holds the :class:`RosBackend`, the panel registry, and the global key
bindings. Each panel is implemented as a self-contained widget under
``lazyros.widgets`` and registered here.
"""

from __future__ import annotations

import logging

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Header, TabbedContent, TabPane

from lazyros.config import Config
from lazyros.ros.backend import RosBackend, RosUnavailable
from lazyros.widgets.actions_panel import ActionsPanel
from lazyros.widgets.bags_panel import BagsPanel
from lazyros.widgets.command_palette import CommandPalette
from lazyros.widgets.help_screen import HelpScreen
from lazyros.widgets.interfaces_panel import InterfacesPanel
from lazyros.widgets.nodes_panel import NodesPanel
from lazyros.widgets.params_panel import ParamsPanel
from lazyros.widgets.plot_panel import PlotPanel
from lazyros.widgets.services_panel import ServicesPanel
from lazyros.widgets.status_bar import StatusBar
from lazyros.widgets.tf_panel import TfPanel
from lazyros.widgets.topics_panel import TopicsPanel

log = logging.getLogger(__name__)


class LazyrosApp(App[int]):
    """Main Textual application."""

    CSS_PATH = "app.tcss"
    TITLE = "lazyros"
    SUB_TITLE = "ROS 2 TUI"

    BINDINGS = [
        Binding("q,ctrl+c", "quit", "Quit"),
        Binding("?", "help", "Help"),
        Binding(":", "command", "Command"),
        Binding("r", "refresh", "Refresh"),
        Binding("1", "tab('topics')", "Topics", show=False),
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
            with TabPane("Topics", id="topics"):
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
        yield StatusBar(id="status")
        yield Footer()

    async def on_mount(self) -> None:
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

    # --------------- background tickers ---------------

    def _refresh_status(self) -> None:
        bar = self.query_one("#status", StatusBar)
        bar.backend_ok = self.backend_ok and self.ros.started
        if not self.ros.started:
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

    def _on_command_submitted(self, raw: str | None) -> None:
        if not raw:
            return
        parts = raw.strip().split()
        cmd, args = parts[0], parts[1:]
        if cmd in ("q", "quit", "exit"):
            self.exit(0)
        elif cmd == "topic" and args:
            self.action_tab("topics")
            try:
                tp = self.query_one(TopicsPanel)
                tp.filter_text = args[0]
            except Exception:
                pass
        elif cmd == "node" and args:
            self.action_tab("nodes")
        elif cmd == "param" and len(args) >= 1:
            self.action_tab("params")
        elif cmd == "plot" and len(args) >= 2:
            topic, path = args[0], args[1]
            self.add_plot_series(topic, path)
        elif cmd == "record":
            self.action_tab("bags")
        elif cmd == "help":
            self.action_help()
        else:
            self.push_status(f"unknown command: {raw}")
