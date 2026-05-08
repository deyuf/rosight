"""Central ROS 2 backend.

Owns one ``rclpy`` node and a multi-threaded executor. Provides a thread-safe
API for the TUI to:

* discover topics / nodes / services / actions / parameters,
* dynamically subscribe to a topic with auto-negotiated QoS,
* dynamically publish a message,
* call services and send action goals,
* read/write parameters.

``rclpy`` is imported lazily inside :meth:`RosBackend.start` so the rest of
the codebase remains importable in environments without ROS 2 (CI, doc
builds, unit tests).
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lazyros.ros import qos as qos_mod
from lazyros.ros.qos import QoSSpec
from lazyros.ros.stats import BandwidthMonitor, RateMonitor, estimate_msg_size

log = logging.getLogger(__name__)


class RosUnavailable(RuntimeError):
    """Raised when an operation requires rclpy but it isn't installed."""


def ros_available() -> bool:
    """Return True if rclpy can be imported in the current environment."""
    try:
        import rclpy  # noqa: F401
    except ImportError:
        return False
    return True


# ---------------------------------------------------------------------------
# Discovery records (plain data, decoupled from rclpy)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TopicInfo:
    name: str
    types: tuple[str, ...]
    publisher_count: int = 0
    subscriber_count: int = 0

    @property
    def primary_type(self) -> str:
        return self.types[0] if self.types else "?"


@dataclass(frozen=True, slots=True)
class NodeInfo:
    name: str
    namespace: str

    @property
    def fqn(self) -> str:
        if self.namespace in ("", "/"):
            return f"/{self.name}"
        return f"{self.namespace}/{self.name}".replace("//", "/")


@dataclass(frozen=True, slots=True)
class ServiceInfo:
    name: str
    types: tuple[str, ...]

    @property
    def primary_type(self) -> str:
        return self.types[0] if self.types else "?"


@dataclass(frozen=True, slots=True)
class ActionInfo:
    name: str
    types: tuple[str, ...]

    @property
    def primary_type(self) -> str:
        return self.types[0] if self.types else "?"


@dataclass(frozen=True, slots=True)
class ParameterValue:
    name: str
    type_name: str
    value: Any


# ---------------------------------------------------------------------------
# Active subscription handle
# ---------------------------------------------------------------------------


@dataclass
class Subscription:
    topic: str
    type_name: str
    rate: RateMonitor = field(default_factory=RateMonitor)
    bandwidth: BandwidthMonitor = field(default_factory=BandwidthMonitor)
    last_msg: Any = None
    last_msg_ts: float = 0.0
    callbacks: list[Callable[[Any], None]] = field(default_factory=list)
    _handle: Any = None  # rclpy Subscription


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class RosBackend:
    """Thread-safe facade over rclpy.

    Use as a context manager::

        with RosBackend(node_name="lazyros") as ros:
            ros.list_topics()
    """

    NODE_NAME_DEFAULT = "lazyros"

    def __init__(
        self,
        node_name: str = NODE_NAME_DEFAULT,
        *,
        domain_id: int | None = None,
        default_depth: int = 10,
    ) -> None:
        self.node_name = node_name
        self.domain_id = domain_id
        self.default_depth = default_depth

        self._lock = threading.RLock()
        self._subscriptions: dict[str, Subscription] = {}
        self._started = False
        self._spin_thread: threading.Thread | None = None
        self._executor: Any = None
        self._node: Any = None
        self._rclpy: Any = None
        self._context: Any = None

    # ----- lifecycle -----------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            try:
                import rclpy
                from rclpy.executors import MultiThreadedExecutor
            except ImportError as e:  # pragma: no cover — env-dependent
                raise RosUnavailable(
                    "rclpy is not installed. Source your ROS 2 workspace, e.g. "
                    "`source /opt/ros/<distro>/setup.bash`, then retry."
                ) from e

            self._rclpy = rclpy
            self._context = rclpy.Context()
            init_args: dict[str, Any] = {"context": self._context}
            if self.domain_id is not None:
                init_args["domain_id"] = self.domain_id
            try:
                rclpy.init(**init_args)
            except TypeError:
                # Older rclpy without domain_id kwarg
                rclpy.init(context=self._context)

            self._node = rclpy.create_node(self.node_name, context=self._context)
            self._executor = MultiThreadedExecutor(num_threads=4, context=self._context)
            self._executor.add_node(self._node)
            self._spin_thread = threading.Thread(
                target=self._spin, name="lazyros-ros-executor", daemon=True
            )
            self._spin_thread.start()
            self._started = True
            log.info("rclpy backend started as %s", self.node_name)

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            try:
                # Tear down subs first
                for sub in list(self._subscriptions.values()):
                    self._destroy_sub(sub)
                self._subscriptions.clear()
                if self._executor is not None:
                    self._executor.shutdown()
                if self._node is not None:
                    self._node.destroy_node()
                if self._rclpy is not None and self._context is not None:
                    try:
                        self._rclpy.shutdown(context=self._context)
                    except Exception:
                        pass
            finally:
                self._started = False
                self._spin_thread = None
                self._executor = None
                self._node = None
            log.info("rclpy backend stopped")

    def __enter__(self) -> RosBackend:
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()

    def _spin(self) -> None:
        try:
            self._executor.spin()
        except Exception:
            log.exception("executor stopped with error")

    # ----- discovery -----------------------------------------------------

    @property
    def started(self) -> bool:
        return self._started

    def _require_node(self):
        if not self._started or self._node is None:
            raise RosUnavailable("backend not started")
        return self._node

    def list_topics(self) -> list[TopicInfo]:
        """Return all topics visible on the network."""
        node = self._require_node()
        try:
            raw = node.get_topic_names_and_types()
        except Exception:
            log.exception("get_topic_names_and_types failed")
            return []
        out: list[TopicInfo] = []
        for name, types in raw:
            try:
                pubs = node.count_publishers(name)
                subs = node.count_subscribers(name)
            except Exception:
                pubs = subs = 0
            out.append(
                TopicInfo(
                    name=name,
                    types=tuple(types),
                    publisher_count=pubs,
                    subscriber_count=subs,
                )
            )
        out.sort(key=lambda t: t.name)
        return out

    def list_nodes(self) -> list[NodeInfo]:
        node = self._require_node()
        try:
            raw = node.get_node_names_and_namespaces()
        except Exception:
            log.exception("get_node_names failed")
            return []
        return sorted(
            (NodeInfo(name=n, namespace=ns) for n, ns in raw),
            key=lambda n: n.fqn,
        )

    def list_services(self) -> list[ServiceInfo]:
        node = self._require_node()
        try:
            raw = node.get_service_names_and_types()
        except Exception:
            return []
        return sorted(
            (ServiceInfo(name=n, types=tuple(t)) for n, t in raw),
            key=lambda s: s.name,
        )

    def list_actions(self) -> list[ActionInfo]:
        node = self._require_node()
        try:
            from rclpy.action import get_action_names_and_types  # type: ignore

            raw = get_action_names_and_types(node)
        except Exception:
            return []
        return sorted(
            (ActionInfo(name=n, types=tuple(t)) for n, t in raw),
            key=lambda a: a.name,
        )

    def node_info(self, fqn: str) -> dict[str, list[tuple[str, tuple[str, ...]]]]:
        """Return pub/sub/srv/action endpoints for a specific node."""
        node = self._require_node()
        ns, _, name = fqn.rpartition("/")
        ns = ns or "/"
        out: dict[str, list[tuple[str, tuple[str, ...]]]] = {
            "publishers": [],
            "subscribers": [],
            "service_servers": [],
            "service_clients": [],
            "action_servers": [],
            "action_clients": [],
        }
        try:
            out["publishers"] = [
                (n, tuple(t)) for n, t in node.get_publisher_names_and_types_by_node(name, ns)
            ]
        except Exception:
            pass
        try:
            out["subscribers"] = [
                (n, tuple(t)) for n, t in node.get_subscriber_names_and_types_by_node(name, ns)
            ]
        except Exception:
            pass
        try:
            out["service_servers"] = [
                (n, tuple(t)) for n, t in node.get_service_names_and_types_by_node(name, ns)
            ]
        except Exception:
            pass
        try:
            out["service_clients"] = [
                (n, tuple(t)) for n, t in node.get_client_names_and_types_by_node(name, ns)
            ]
        except Exception:
            pass
        return out

    def publisher_qos(self, topic: str) -> list[QoSSpec]:
        node = self._require_node()
        try:
            infos = node.get_publishers_info_by_topic(topic)
        except Exception:
            return []
        return [qos_mod.from_rclpy(i.qos_profile) for i in infos]

    # ----- dynamic subscribe --------------------------------------------

    def subscribe(
        self,
        topic: str,
        type_name: str | None = None,
        on_message: Callable[[Any], None] | None = None,
        spec: QoSSpec | None = None,
    ) -> Subscription:
        """Subscribe to ``topic``; reuses an existing subscription if any."""
        from lazyros.ros.introspection import get_message_class

        node = self._require_node()

        with self._lock:
            existing = self._subscriptions.get(topic)
            if existing is not None:
                if on_message:
                    existing.callbacks.append(on_message)
                return existing

            # Resolve type
            if type_name is None:
                topics = {t.name: t for t in self.list_topics()}
                ti = topics.get(topic)
                if ti is None or not ti.types:
                    raise ValueError(f"topic {topic!r} has no known type")
                type_name = ti.primary_type
            msg_cls = get_message_class(type_name)

            # QoS auto-match
            if spec is None:
                spec = qos_mod.negotiate(self.publisher_qos(topic), self.default_depth)
            profile = qos_mod.to_rclpy(spec)

            sub = Subscription(topic=topic, type_name=type_name)
            if on_message:
                sub.callbacks.append(on_message)

            def _cb(msg: Any) -> None:
                ts = time.monotonic()
                sub.rate.tick(ts)
                sub.bandwidth.tick(estimate_msg_size(msg), ts)
                sub.last_msg = msg
                sub.last_msg_ts = ts
                for cb in list(sub.callbacks):
                    try:
                        cb(msg)
                    except Exception:
                        log.exception("subscriber callback raised")

            sub._handle = node.create_subscription(msg_cls, topic, _cb, profile)
            self._subscriptions[topic] = sub
            return sub

    def unsubscribe(self, topic: str) -> None:
        with self._lock:
            sub = self._subscriptions.pop(topic, None)
        if sub is not None:
            self._destroy_sub(sub)

    def _destroy_sub(self, sub: Subscription) -> None:
        try:
            if sub._handle is not None and self._node is not None:
                self._node.destroy_subscription(sub._handle)
        except Exception:
            log.exception("destroy_subscription failed")
        finally:
            sub._handle = None
            sub.callbacks.clear()

    def get_subscription(self, topic: str) -> Subscription | None:
        with self._lock:
            return self._subscriptions.get(topic)

    def active_subscriptions(self) -> list[Subscription]:
        with self._lock:
            return list(self._subscriptions.values())

    # ----- publish one-shot ---------------------------------------------

    def publish_once(
        self,
        topic: str,
        type_name: str,
        message: Any,
        spec: QoSSpec | None = None,
    ) -> None:
        from lazyros.ros.introspection import get_message_class

        node = self._require_node()
        msg_cls = get_message_class(type_name)
        if not isinstance(message, msg_cls):
            raise TypeError(f"message must be {type_name}, got {type(message).__name__}")
        spec = spec or qos_mod.DEFAULT.with_depth(self.default_depth)
        profile = qos_mod.to_rclpy(spec)
        pub = node.create_publisher(msg_cls, topic, profile)
        try:
            pub.publish(message)
            # Allow DDS discovery and delivery before destroying.
            time.sleep(0.05)
        finally:
            node.destroy_publisher(pub)

    # ----- service / parameters -----------------------------------------

    def call_service(
        self,
        service: str,
        type_name: str,
        request: Any,
        timeout: float = 5.0,
    ) -> Any:
        from lazyros.ros.introspection import get_service_class

        node = self._require_node()
        srv_cls = get_service_class(type_name)
        client = node.create_client(srv_cls, service)
        try:
            if not client.wait_for_service(timeout_sec=timeout):
                raise TimeoutError(f"service {service!r} unavailable")
            future = client.call_async(request)
            deadline = time.monotonic() + timeout
            while not future.done():
                if time.monotonic() > deadline:
                    raise TimeoutError(f"service call to {service!r} timed out")
                time.sleep(0.01)
            return future.result()
        finally:
            node.destroy_client(client)

    def list_parameters(self, target_node: str) -> list[str]:
        try:  # pragma: no cover — needs ROS network
            from rcl_interfaces.srv import ListParameters

            req = ListParameters.Request()
            req.depth = 0
            resp = self.call_service(
                f"{target_node}/list_parameters",
                "rcl_interfaces/srv/ListParameters",
                req,
            )
            return list(resp.result.names)
        except Exception:
            return []

    def get_parameters(
        self, target_node: str, names: list[str]
    ) -> list[ParameterValue]:  # pragma: no cover — needs ROS network
        from rcl_interfaces.srv import GetParameters

        req = GetParameters.Request()
        req.names = names
        resp = self.call_service(
            f"{target_node}/get_parameters",
            "rcl_interfaces/srv/GetParameters",
            req,
        )
        out: list[ParameterValue] = []
        for n, v in zip(names, resp.values, strict=False):
            out.append(ParameterValue(n, _param_type_name(v.type), _param_value(v)))
        return out

    def set_parameter(
        self, target_node: str, name: str, value: Any
    ) -> bool:  # pragma: no cover — needs ROS network
        from rcl_interfaces.msg import Parameter
        from rcl_interfaces.msg import ParameterValue as PV
        from rcl_interfaces.srv import SetParameters

        pv = PV()
        if isinstance(value, bool):
            pv.type = 1
            pv.bool_value = value
        elif isinstance(value, int):
            pv.type = 2
            pv.integer_value = value
        elif isinstance(value, float):
            pv.type = 3
            pv.double_value = value
        elif isinstance(value, str):
            pv.type = 4
            pv.string_value = value
        else:
            raise TypeError(f"unsupported parameter type: {type(value).__name__}")
        req = SetParameters.Request()
        param = Parameter()
        param.name = name
        param.value = pv
        req.parameters = [param]
        resp = self.call_service(
            f"{target_node}/set_parameters",
            "rcl_interfaces/srv/SetParameters",
            req,
        )
        return all(r.successful for r in resp.results)


def _param_type_name(t: int) -> str:  # pragma: no cover
    return {
        0: "not_set",
        1: "bool",
        2: "integer",
        3: "double",
        4: "string",
        5: "byte_array",
        6: "bool_array",
        7: "integer_array",
        8: "double_array",
        9: "string_array",
    }.get(int(t), "unknown")


def _param_value(v: Any) -> Any:  # pragma: no cover
    t = int(v.type)
    if t == 1:
        return v.bool_value
    if t == 2:
        return v.integer_value
    if t == 3:
        return v.double_value
    if t == 4:
        return v.string_value
    if t == 5:
        return list(v.byte_array_value)
    if t == 6:
        return list(v.bool_array_value)
    if t == 7:
        return list(v.integer_array_value)
    if t == 8:
        return list(v.double_array_value)
    if t == 9:
        return list(v.string_array_value)
    return None
