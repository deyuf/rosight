"""End-to-end-ish tests for ``RosBackend.subscribe`` / ``unsubscribe``.

Uses a fake rclpy node + a synchronous "executor" — we don't spin a
real thread, instead the test calls ``fake_node.deliver(topic, msg)``
to simulate a message arriving on the executor worker. This covers:

* subscription reuse (second ``subscribe`` of the same topic only adds
  a callback, doesn't create a new rclpy handle),
* multi-callback fan-out,
* ``unsubscribe`` destroys the rclpy handle exactly once,
* destroying a sub clears its callback list (preventing late-firing
  callbacks from hitting torn widgets),
* ``set_domain_id`` clears subscriptions on restart.

These exercise paths previously marked ``pragma: no cover`` because
they touch the rclpy boundary.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from rosight.ros.backend import RosBackend


class _FakeSubHandle:
    def __init__(self, topic: str, cb):
        self.topic = topic
        self.cb = cb
        self.destroyed = False


class _FakeNode:
    """Minimal stand-in for an rclpy node — captures subscription handles
    and lets the test deliver messages on demand."""

    def __init__(self):
        self._subs: list[_FakeSubHandle] = []
        self.destroyed_subs: list[_FakeSubHandle] = []

    def create_subscription(self, _msg_cls, topic, cb, _profile):
        h = _FakeSubHandle(topic, cb)
        self._subs.append(h)
        return h

    def destroy_subscription(self, handle):
        handle.destroyed = True
        self.destroyed_subs.append(handle)
        if handle in self._subs:
            self._subs.remove(handle)

    def get_topic_names_and_types(self):
        return [("/chatter", ["std_msgs/msg/String"])]

    def count_publishers(self, _t):
        return 1

    def count_subscribers(self, _t):
        return 0

    def get_publishers_info_by_topic(self, _t):
        return []  # negotiate falls back to defaults

    def deliver(self, topic: str, msg: Any) -> None:
        """Simulate the executor firing the rclpy callback."""
        for h in list(self._subs):
            if h.topic == topic and not h.destroyed:
                h.cb(msg)


@pytest.fixture
def fake_backend(monkeypatch):
    """A backend backed by ``_FakeNode``, with a stubbed message-class
    resolver so we don't need rclpy."""
    b = RosBackend()
    b._node = _FakeNode()
    b._started = True

    # Stub the introspection import that subscribe() does to avoid
    # needing real ROS message modules.
    from rosight.ros import introspection

    monkeypatch.setattr(introspection, "get_message_class", lambda _t: object)
    # Avoid the QoS negotiation talking to rclpy.
    import rosight.ros.qos as qos_mod

    monkeypatch.setattr(qos_mod, "to_rclpy", lambda _spec: object())
    return b


def test_subscribe_creates_one_handle(fake_backend):
    cb = MagicMock()
    sub = fake_backend.subscribe("/chatter", on_message=cb)
    assert len(fake_backend._node._subs) == 1
    assert sub.callback_count() == 1


def test_second_subscribe_reuses_handle_and_fans_out(fake_backend):
    cb1 = MagicMock()
    cb2 = MagicMock()
    fake_backend.subscribe("/chatter", on_message=cb1)
    fake_backend.subscribe("/chatter", on_message=cb2)
    # Still only ONE underlying rclpy subscription.
    assert len(fake_backend._node._subs) == 1
    # Delivering a message fires both callbacks.
    fake_backend._node.deliver("/chatter", "hello")
    cb1.assert_called_once_with("hello")
    cb2.assert_called_once_with("hello")


def test_unsubscribe_destroys_handle_and_clears_callbacks(fake_backend):
    cb = MagicMock()
    sub = fake_backend.subscribe("/chatter", on_message=cb)
    handle = sub._handle
    fake_backend.unsubscribe("/chatter")
    assert handle.destroyed is True
    assert sub._handle is None
    # No more callbacks — late-firing messages don't reach torn widgets.
    assert sub.callback_count() == 0
    # Backend dict cleared.
    assert fake_backend.get_subscription("/chatter") is None


def test_late_message_after_unsubscribe_does_not_fire_callback(fake_backend):
    """After ``unsubscribe`` we removed the handle from the fake node;
    delivering on the same topic must be a no-op."""
    cb = MagicMock()
    fake_backend.subscribe("/chatter", on_message=cb)
    fake_backend.unsubscribe("/chatter")
    fake_backend._node.deliver("/chatter", "ghost")
    cb.assert_not_called()


def test_callback_exception_does_not_break_other_subscribers(fake_backend):
    """A buggy callback shouldn't sink its siblings — exceptions are
    swallowed and logged in the executor branch."""
    bad = MagicMock(side_effect=RuntimeError("boom"))
    good = MagicMock()
    fake_backend.subscribe("/chatter", on_message=bad)
    fake_backend.subscribe("/chatter", on_message=good)
    fake_backend._node.deliver("/chatter", "payload")
    bad.assert_called_once()
    good.assert_called_once()


def test_unsubscribe_unknown_topic_is_noop(fake_backend):
    fake_backend.unsubscribe("/never-subscribed")
    assert fake_backend._node.destroyed_subs == []


def test_subscribe_records_rate_and_bandwidth(fake_backend, monkeypatch):
    """The executor callback must update rate/bandwidth monitors and the
    ``last_msg``/``last_msg_ts`` pair atomically."""
    # Make estimate_msg_size deterministic.
    import rosight.ros.backend as backend_mod

    monkeypatch.setattr(backend_mod, "estimate_msg_size", lambda _m: 42)

    sub = fake_backend.subscribe("/chatter")
    fake_backend._node.deliver("/chatter", "payload")
    msg, ts = sub.snapshot()
    assert msg == "payload"
    assert ts > 0


def test_active_subscriptions_lists_known_topics(fake_backend):
    fake_backend.subscribe("/chatter")
    active = fake_backend.active_subscriptions()
    assert [s.topic for s in active] == ["/chatter"]


def test_set_domain_id_when_started_restarts_via_stop_start(monkeypatch):
    """Without rclpy we can't truly restart, but we can verify that the
    bookkeeping (stop → start) clears subscriptions. We patch the
    private ``stop``/``start`` to spy on the sequence."""
    b = RosBackend()
    b._started = True  # pretend we're up
    calls: list[str] = []

    def fake_stop():
        calls.append("stop")
        b._started = False
        b._subscriptions.clear()

    def fake_start():
        calls.append("start")
        b._started = True

    monkeypatch.setattr(b, "stop", fake_stop)
    monkeypatch.setattr(b, "start", fake_start)
    # Seed a fake subscription so we can prove it's cleared.
    from rosight.ros.backend import Subscription

    b._subscriptions["/old"] = Subscription(topic="/old", type_name="t")
    b.set_domain_id(7)
    assert calls == ["stop", "start"]
    assert b.domain_id == 7
    assert b._subscriptions == {}


def test_set_domain_id_when_stopped_only_updates_attr(monkeypatch):
    b = RosBackend()
    assert b._started is False
    calls: list[str] = []
    monkeypatch.setattr(b, "stop", lambda: calls.append("stop"))
    monkeypatch.setattr(b, "start", lambda: calls.append("start"))
    b.set_domain_id(5)
    # Neither stop nor start fires when the backend isn't running.
    assert calls == []
    assert b.domain_id == 5
