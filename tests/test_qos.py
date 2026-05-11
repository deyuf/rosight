from __future__ import annotations

from rosight.ros.qos import (
    DEFAULT,
    SENSOR_DATA,
    Durability,
    History,
    QoSSpec,
    Reliability,
    negotiate,
)


def test_default_is_reliable_volatile_keep_last():
    assert DEFAULT.reliability == Reliability.RELIABLE
    assert DEFAULT.durability == Durability.VOLATILE
    assert DEFAULT.history == History.KEEP_LAST


def test_sensor_data_is_best_effort():
    assert SENSOR_DATA.reliability == Reliability.BEST_EFFORT


def test_negotiate_no_publishers_returns_default():
    spec = negotiate([], default_depth=7)
    assert spec.depth == 7
    assert spec.reliability == Reliability.RELIABLE


def test_negotiate_downgrades_to_best_effort_if_any_pub_is():
    pubs = [
        QoSSpec(reliability=Reliability.RELIABLE),
        QoSSpec(reliability=Reliability.BEST_EFFORT),
    ]
    spec = negotiate(pubs)
    assert spec.reliability == Reliability.BEST_EFFORT


def test_negotiate_keeps_reliable_when_all_pubs_reliable():
    pubs = [
        QoSSpec(reliability=Reliability.RELIABLE),
        QoSSpec(reliability=Reliability.RELIABLE),
    ]
    assert negotiate(pubs).reliability == Reliability.RELIABLE


def test_negotiate_uses_transient_local_only_when_all_pubs_transient():
    transient = QoSSpec(durability=Durability.TRANSIENT_LOCAL)
    volatile = QoSSpec(durability=Durability.VOLATILE)
    assert negotiate([transient, transient]).durability == Durability.TRANSIENT_LOCAL
    assert negotiate([transient, volatile]).durability == Durability.VOLATILE


def test_with_depth_returns_new_instance():
    a = QoSSpec()
    b = a.with_depth(42)
    assert a.depth != b.depth
    assert b.depth == 42
