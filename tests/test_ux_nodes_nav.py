"""Nodes panel endpoint tree: enter on an entry jumps to that topic/service."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, TabbedContent, Tree

from rosight.app import RosightApp
from rosight.ros.backend import NodeInfo, RosBackend, ServiceInfo, TopicInfo
from rosight.ros.discovery import GraphSnapshot
from rosight.widgets.nodes_panel import NodesPanel
from rosight.widgets.services_panel import ServicesPanel
from rosight.widgets.topics_panel import TopicsPanel


class _Ros:
    started = True
    executor_alive = True
    domain_id = 0

    def graph_snapshot(self):
        return GraphSnapshot(
            topics=(
                TopicInfo("/a", ("std_msgs/msg/String",)),
                TopicInfo("/odom", ("nav_msgs/msg/Odometry",)),
            ),
            nodes=(NodeInfo("driver", "/"),),
            services=(
                ServiceInfo("/x", ("std_srvs/srv/Empty",)),
                ServiceInfo("/driver/reset", ("std_srvs/srv/Trigger",)),
            ),
            generation=1,
        )

    def node_info(self, _fqn):
        return {
            "publishers": [("/odom", ("nav_msgs/msg/Odometry",))],
            "subscribers": [],
            "service_servers": [("/driver/reset", ("std_srvs/srv/Trigger",))],
            "service_clients": [],
        }

    def active_subscriptions(self):
        return []

    def get_subscription(self, _t):
        return None

    def stop(self):
        pass


async def _open_node(pilot) -> Tree:
    pilot.app.ros = _Ros()  # type: ignore[assignment]
    pilot.app.query_one(TabbedContent).active = "nodes"
    for _ in range(3):
        await pilot.pause()
    panel = pilot.app.query_one(NodesPanel)
    panel.selected = "/driver"
    panel.action_info()
    await pilot.pause()
    return panel.query_one("#node-detail", Tree)


def _leaf(tree: Tree, name: str):
    for section in tree.root.children:
        for leaf in section.children:
            if leaf.data and leaf.data[1] == name:
                return leaf
    raise AssertionError(name)


@pytest.mark.asyncio
async def test_endpoint_tree_sections():
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
        tree = await _open_node(pilot)
        labels = [str(s.label.plain) for s in tree.root.children]
        assert labels[0].startswith("Publishers") and "(1)" in labels[0]
        assert labels[1].startswith("Subscribers") and "(0)" in labels[1]
        assert _leaf(tree, "/odom").data == ("topic", "/odom")


@pytest.mark.asyncio
async def test_enter_on_publisher_jumps_to_topic():
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
        tree = await _open_node(pilot)
        tree.focus()
        tree.move_cursor(_leaf(tree, "/odom"))
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(4):
            await pilot.pause()
        assert pilot.app.query_one(TabbedContent).active == "topics"
        topics = pilot.app.query_one(TopicsPanel)
        assert topics.selected_topic == "/odom"
        table = topics.query_one("#topics-table", DataTable)
        assert table.has_focus
        assert str(table.ordered_rows[table.cursor_row].key.value) == "/odom"


@pytest.mark.asyncio
async def test_enter_on_service_server_jumps_to_service_even_if_filtered():
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
        tree = await _open_node(pilot)
        services = pilot.app.query_one(ServicesPanel)
        services.filter_text = "zzz"  # stale filter must be cleared
        tree.focus()
        tree.move_cursor(_leaf(tree, "/driver/reset"))
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(4):
            await pilot.pause()
        assert pilot.app.query_one(TabbedContent).active == "services"
        assert services.filter_text == ""
        assert services.selected == "/driver/reset"


@pytest.mark.asyncio
async def test_goto_unknown_topic_reports_in_status():
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
        pilot.app.ros = _Ros()  # type: ignore[assignment]
        pilot.app.goto_topic("/ghost")
        for _ in range(3):
            await pilot.pause()
        assert "not in the list" in pilot.app.query_one("#status").message


@pytest.mark.asyncio
async def test_node_command_selects_node_and_shows_endpoints():
    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
        pilot.app.ros = _Ros()  # type: ignore[assignment]
        pilot.app._on_command_submitted("node driver")  # leading slash optional
        for _ in range(5):
            await pilot.pause()
        assert pilot.app.query_one(TabbedContent).active == "nodes"
        panel = pilot.app.query_one(NodesPanel)
        assert panel.selected == "/driver"
        tree = panel.query_one("#node-detail", Tree)
        assert _leaf(tree, "/odom") is not None


@pytest.mark.asyncio
async def test_param_command_loads_that_node():
    from rosight.widgets.params_panel import ParamsPanel

    loaded: list[str] = []

    class _ParamRos(_Ros):
        def list_parameters(self, node):
            loaded.append(node)
            return []

        def get_parameters(self, node, names):
            return []

    async with RosightApp(ros=RosBackend()).run_test(headless=True, size=(160, 45)) as pilot:
        pilot.app.ros = _ParamRos()  # type: ignore[assignment]
        pilot.app._on_command_submitted("param /driver")
        for _ in range(8):
            await pilot.pause()
        assert pilot.app.query_one(TabbedContent).active == "params"
        assert pilot.app.query_one(ParamsPanel).selected_node == "/driver"
        assert loaded == ["/driver"]
