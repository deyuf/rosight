"""Tests for raw (serialized-bytes) subscriptions with lazy decoding.

A fake rclpy node records the kwargs ``create_subscription`` was called
with, and a fake deserializer counts how often bytes are decoded. The key
property: the executor thread never decodes unless a callback needs it,
and the UI decodes each received message at most once.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

import rosight.ros.backend as backend_mod
from rosight.ros.backend import RosBackend, Subscription


class _Handle:
    def __init__(self, topic: str, cb, kwargs: dict):
        self.topic = topic
        self.cb = cb
        self.kwargs = kwargs


class _Node:
    """Fake node; ``accept`` lists the optional kwargs it supports."""

    def __init__(self, accept: tuple[str, ...] = ("raw", "event_callbacks")):
        self.accept = accept
        self.handles: list[_Handle] = []

    def create_subscription(self, _cls, topic, cb, _profile, **kwargs):
        unknown = set(kwargs) - set(self.accept)
        if unknown:
            raise TypeError(f"unexpected keyword argument {sorted(unknown)[0]!r}")
        h = _Handle(topic, cb, kwargs)
        self.handles.append(h)
        return h

    def destroy_subscription(self, _h):
        pass

    def get_publishers_info_by_topic(self, _t):
        return []

    def deliver(self, payload: Any) -> None:
        for h in self.handles:
            h.cb(payload)

    def fire_event(self, info: Any) -> None:
        for h in self.handles:
            ev = h.kwargs.get("event_callbacks")
            if ev is not None:
                ev.incompatible_qos(info)


class _EventCallbacks:
    def __init__(self, incompatible_qos=None):
        self.incompatible_qos = incompatible_qos


class _Decoder:
    def __init__(self, fail_on: bytes | None = None):
        self.calls = 0
        self.fail_on = fail_on

    def __call__(self, data: bytes, _cls: Any) -> Any:
        self.calls += 1
        if data == self.fail_on:
            raise ValueError("corrupt CDR")
        return SimpleNamespace(data=data.decode())


@pytest.fixture
def make_backend(monkeypatch):
    import rosight.ros.qos as qos_mod
    from rosight.ros import introspection

    monkeypatch.setattr(introspection, "get_message_class", lambda _t: object)
    monkeypatch.setattr(qos_mod, "to_rclpy", lambda _spec: object())

    def _make(node: _Node, *, decoder=None, events=True) -> RosBackend:
        b = RosBackend()
        b._node = node
        b._started = True
        b._deserialize_fn = decoder
        b._event_callbacks_cls = _EventCallbacks if events else None
        return b

    return _make


def test_raw_mode_requested_when_deserializer_available(make_backend):
    node = _Node()
    b = make_backend(node, decoder=_Decoder())
    sub = b.subscribe("/chatter", "std_msgs/msg/String")
    assert sub.raw_mode
    assert node.handles[0].kwargs.get("raw") is True
    assert "event_callbacks" in node.handles[0].kwargs


def test_executor_path_does_not_decode(make_backend):
    node = _Node()
    dec = _Decoder()
    b = make_backend(node, decoder=dec)
    sub = b.subscribe("/chatter", "std_msgs/msg/String")
    for i in range(100):
        node.deliver(f"msg{i}".encode())
    assert dec.calls == 0, "raw ingestion must not deserialize"
    assert sub.rate.sample().samples == 100


def test_bandwidth_uses_exact_byte_length(make_backend):
    node = _Node()
    b = make_backend(node, decoder=_Decoder())
    sub = b.subscribe("/chatter", "std_msgs/msg/String")
    for _ in range(10):
        node.deliver(b"x" * 1000)
    assert sub.bandwidth.sample().avg_msg_size == pytest.approx(1000)


def test_snapshot_decodes_latest_once_and_caches(make_backend):
    node = _Node()
    dec = _Decoder()
    b = make_backend(node, decoder=dec)
    sub = b.subscribe("/chatter", "std_msgs/msg/String")
    for i in range(50):
        node.deliver(f"m{i}".encode())
    msg, ts = sub.snapshot()
    assert msg.data == "m49"
    assert ts > 0
    for _ in range(10):
        assert sub.snapshot()[0].data == "m49"
    assert dec.calls == 1, "50 messages + 11 reads must cost exactly one decode"
    node.deliver(b"m50")
    assert sub.last_msg.data == "m50"
    assert dec.calls == 2


def test_callbacks_force_one_decode_shared_with_snapshot(make_backend):
    node = _Node()
    dec = _Decoder()
    b = make_backend(node, decoder=dec)
    got: list[str] = []
    sub = b.subscribe("/chatter", "std_msgs/msg/String", on_message=lambda m: got.append(m.data))
    node.deliver(b"hello")
    assert got == ["hello"]
    assert sub.snapshot()[0].data == "hello"
    assert dec.calls == 1


def test_decode_failure_keeps_previous_message(make_backend):
    node = _Node()
    dec = _Decoder(fail_on=b"bad")
    b = make_backend(node, decoder=dec)
    sub = b.subscribe("/chatter", "std_msgs/msg/String")
    node.deliver(b"good")
    assert sub.snapshot()[0].data == "good"
    node.deliver(b"bad")
    msg, _ = sub.snapshot()
    assert msg.data == "good"
    assert sub.decode_errors == 1


def test_falls_back_to_decoded_when_raw_unsupported(make_backend, monkeypatch):
    monkeypatch.setattr(backend_mod, "estimate_msg_size", lambda _m: 7)
    node = _Node(accept=("event_callbacks",))
    b = make_backend(node, decoder=_Decoder())
    sub = b.subscribe("/chatter", "std_msgs/msg/String")
    assert not sub.raw_mode
    assert "raw" not in node.handles[0].kwargs
    assert "event_callbacks" in node.handles[0].kwargs
    node.deliver(SimpleNamespace(data="obj"))
    assert sub.last_msg.data == "obj"


def test_keeps_raw_when_only_event_callbacks_unsupported(make_backend):
    node = _Node(accept=("raw",))
    b = make_backend(node, decoder=_Decoder())
    sub = b.subscribe("/chatter", "std_msgs/msg/String")
    assert sub.raw_mode
    assert node.handles[0].kwargs == {"raw": True}


def test_plain_node_gets_plain_subscription(make_backend):
    node = _Node(accept=())
    b = make_backend(node, decoder=_Decoder())
    sub = b.subscribe("/chatter", "std_msgs/msg/String")
    assert not sub.raw_mode
    assert node.handles[0].kwargs == {}


def test_decoded_mode_size_estimate_is_throttled(make_backend, monkeypatch):
    calls = {"n": 0}

    def counting(_m):
        calls["n"] += 1
        return 64

    monkeypatch.setattr(backend_mod, "estimate_msg_size", counting)
    node = _Node(accept=())
    b = make_backend(node)
    sub = b.subscribe("/chatter", "std_msgs/msg/String")
    for i in range(200):
        node.deliver(SimpleNamespace(data=str(i)))
    assert calls["n"] == 1, "re-serializing every message is what we're avoiding"
    assert sub.bandwidth.sample().avg_msg_size == pytest.approx(64)


def test_incompatible_qos_event_is_recorded(make_backend):
    node = _Node()
    b = make_backend(node, decoder=_Decoder())
    sub = b.subscribe("/chatter", "std_msgs/msg/String")
    assert sub.qos_incompatible is None
    node.fire_event(
        SimpleNamespace(total_count=3, last_policy_kind=SimpleNamespace(name="RELIABILITY"))
    )
    assert sub.qos_incompatible == "RELIABILITY"
    assert sub.qos_incompatible_count == 3


def test_incompatible_qos_handles_odd_policy_values():
    sub = Subscription("/x", "t")
    sub.on_incompatible_qos(SimpleNamespace(last_policy_kind="RMW_QOS_POLICY_DURABILITY"))
    assert sub.qos_incompatible == "DURABILITY"
    assert sub.qos_incompatible_count == 1
