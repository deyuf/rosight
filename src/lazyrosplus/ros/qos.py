"""QoS helpers — pure logic so it can be unit-tested without rclpy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Reliability(str, Enum):
    SYSTEM_DEFAULT = "system_default"
    RELIABLE = "reliable"
    BEST_EFFORT = "best_effort"
    UNKNOWN = "unknown"


class Durability(str, Enum):
    SYSTEM_DEFAULT = "system_default"
    VOLATILE = "volatile"
    TRANSIENT_LOCAL = "transient_local"
    UNKNOWN = "unknown"


class History(str, Enum):
    SYSTEM_DEFAULT = "system_default"
    KEEP_LAST = "keep_last"
    KEEP_ALL = "keep_all"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class QoSSpec:
    """Plain-data QoS description, decoupled from rclpy."""

    reliability: Reliability = Reliability.RELIABLE
    durability: Durability = Durability.VOLATILE
    history: History = History.KEEP_LAST
    depth: int = 10

    def with_depth(self, depth: int) -> QoSSpec:
        return QoSSpec(self.reliability, self.durability, self.history, depth)


SENSOR_DATA = QoSSpec(
    reliability=Reliability.BEST_EFFORT,
    durability=Durability.VOLATILE,
    history=History.KEEP_LAST,
    depth=5,
)

DEFAULT = QoSSpec()


def negotiate(publisher_specs: list[QoSSpec], default_depth: int = 10) -> QoSSpec:
    """Pick a subscriber QoS that will match every supplied publisher.

    Rules (informal — mirrors the practical heuristic used by the ros2 CLI):

    * If *any* publisher is BEST_EFFORT, the subscriber must also be
      BEST_EFFORT (RELIABLE subscribers don't match BEST_EFFORT publishers).
    * If *all* publishers are TRANSIENT_LOCAL, mirror that to receive latched
      messages; otherwise stay VOLATILE.
    * History is always KEEP_LAST with ``default_depth``.
    """
    if not publisher_specs:
        return DEFAULT.with_depth(default_depth)

    reliability = (
        Reliability.BEST_EFFORT
        if any(s.reliability == Reliability.BEST_EFFORT for s in publisher_specs)
        else Reliability.RELIABLE
    )
    durability = (
        Durability.TRANSIENT_LOCAL
        if all(s.durability == Durability.TRANSIENT_LOCAL for s in publisher_specs)
        else Durability.VOLATILE
    )
    return QoSSpec(
        reliability=reliability,
        durability=durability,
        history=History.KEEP_LAST,
        depth=default_depth,
    )


def to_rclpy(spec: QoSSpec):  # pragma: no cover — requires rclpy
    """Convert a QoSSpec into an :class:`rclpy.qos.QoSProfile`."""
    from rclpy.qos import (
        DurabilityPolicy,
        HistoryPolicy,
        QoSProfile,
        ReliabilityPolicy,
    )

    rmap = {
        Reliability.RELIABLE: ReliabilityPolicy.RELIABLE,
        Reliability.BEST_EFFORT: ReliabilityPolicy.BEST_EFFORT,
        Reliability.SYSTEM_DEFAULT: ReliabilityPolicy.SYSTEM_DEFAULT,
        Reliability.UNKNOWN: ReliabilityPolicy.SYSTEM_DEFAULT,
    }
    dmap = {
        Durability.VOLATILE: DurabilityPolicy.VOLATILE,
        Durability.TRANSIENT_LOCAL: DurabilityPolicy.TRANSIENT_LOCAL,
        Durability.SYSTEM_DEFAULT: DurabilityPolicy.SYSTEM_DEFAULT,
        Durability.UNKNOWN: DurabilityPolicy.SYSTEM_DEFAULT,
    }
    hmap = {
        History.KEEP_LAST: HistoryPolicy.KEEP_LAST,
        History.KEEP_ALL: HistoryPolicy.KEEP_ALL,
        History.SYSTEM_DEFAULT: HistoryPolicy.SYSTEM_DEFAULT,
        History.UNKNOWN: HistoryPolicy.SYSTEM_DEFAULT,
    }
    return QoSProfile(
        reliability=rmap[spec.reliability],
        durability=dmap[spec.durability],
        history=hmap[spec.history],
        depth=spec.depth,
    )


def from_rclpy(profile) -> QoSSpec:  # pragma: no cover — requires rclpy
    from rclpy.qos import DurabilityPolicy, HistoryPolicy, ReliabilityPolicy

    rmap = {
        ReliabilityPolicy.RELIABLE: Reliability.RELIABLE,
        ReliabilityPolicy.BEST_EFFORT: Reliability.BEST_EFFORT,
        ReliabilityPolicy.SYSTEM_DEFAULT: Reliability.SYSTEM_DEFAULT,
    }
    dmap = {
        DurabilityPolicy.VOLATILE: Durability.VOLATILE,
        DurabilityPolicy.TRANSIENT_LOCAL: Durability.TRANSIENT_LOCAL,
        DurabilityPolicy.SYSTEM_DEFAULT: Durability.SYSTEM_DEFAULT,
    }
    hmap = {
        HistoryPolicy.KEEP_LAST: History.KEEP_LAST,
        HistoryPolicy.KEEP_ALL: History.KEEP_ALL,
        HistoryPolicy.SYSTEM_DEFAULT: History.SYSTEM_DEFAULT,
    }
    return QoSSpec(
        reliability=rmap.get(profile.reliability, Reliability.UNKNOWN),
        durability=dmap.get(profile.durability, Durability.UNKNOWN),
        history=hmap.get(profile.history, History.UNKNOWN),
        depth=int(getattr(profile, "depth", 10) or 10),
    )
