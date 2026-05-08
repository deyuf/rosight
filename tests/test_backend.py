"""Backend tests using a mocked rclpy node — no live ROS network required."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lazyros.ros.backend import (
    NodeInfo,
    RosBackend,
    RosUnavailable,
    ServiceInfo,
    TopicInfo,
)


def _backend_with_mock_node():
    b = RosBackend()
    b._node = MagicMock()
    b._started = True
    return b


def test_topic_info_primary_type_default():
    ti = TopicInfo(name="/x", types=())
    assert ti.primary_type == "?"


def test_node_info_fqn_with_namespace():
    assert NodeInfo("a", "/").fqn == "/a"
    assert NodeInfo("a", "/ns").fqn == "/ns/a"


def test_service_info_primary_type():
    s = ServiceInfo("/srv", ("std_srvs/srv/Empty",))
    assert s.primary_type == "std_srvs/srv/Empty"


def test_list_topics_with_mock_node():
    b = _backend_with_mock_node()
    b._node.get_topic_names_and_types.return_value = [
        ("/chatter", ["std_msgs/msg/String"]),
        ("/scan", ["sensor_msgs/msg/LaserScan"]),
    ]
    b._node.count_publishers.return_value = 1
    b._node.count_subscribers.return_value = 0
    out = b.list_topics()
    assert {t.name for t in out} == {"/chatter", "/scan"}
    assert out[0].publisher_count == 1


def test_list_topics_returns_empty_on_error():
    b = _backend_with_mock_node()
    b._node.get_topic_names_and_types.side_effect = RuntimeError("boom")
    assert b.list_topics() == []


def test_list_nodes_sorted():
    b = _backend_with_mock_node()
    b._node.get_node_names_and_namespaces.return_value = [
        ("zeta", "/"),
        ("alpha", "/"),
    ]
    out = b.list_nodes()
    assert [n.name for n in out] == ["alpha", "zeta"]


def test_active_subscriptions_initially_empty():
    b = _backend_with_mock_node()
    assert b.active_subscriptions() == []


def test_unsubscribe_unknown_is_noop():
    b = _backend_with_mock_node()
    b.unsubscribe("/nothing")  # should not raise


def test_require_node_raises_when_unstarted():
    b = RosBackend()
    with pytest.raises(RosUnavailable):
        b._require_node()


def test_node_info_keys_present():
    b = _backend_with_mock_node()
    b._node.get_publisher_names_and_types_by_node.return_value = [("/foo", ["std_msgs/msg/String"])]
    b._node.get_subscriber_names_and_types_by_node.return_value = []
    b._node.get_service_names_and_types_by_node.return_value = []
    b._node.get_client_names_and_types_by_node.return_value = []
    info = b.node_info("/talker")
    assert "publishers" in info
    assert info["publishers"][0][0] == "/foo"
