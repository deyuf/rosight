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

from rosight.ros import qos as qos_mod
from rosight.ros.qos import QoSSpec
from rosight.ros.stats import BandwidthMonitor, RateMonitor, estimate_msg_size

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
    """Live subscription state shared between the rclpy executor and UI.

    The rclpy callback runs on an executor worker thread; widgets read
    state from Textual's event loop. ``_lock`` serializes the few moments
    where both sides touch the same list/fields:

    * the executor appends to ``last_msg`` and iterates ``callbacks``;
    * widgets add/remove callbacks and snapshot ``last_msg`` + ``last_msg_ts``.

    Access ``last_msg`` directly only when you don't need the timestamp
    to match the message; otherwise prefer :meth:`snapshot`.
    """

    topic: str
    type_name: str
    rate: RateMonitor = field(default_factory=RateMonitor)
    bandwidth: BandwidthMonitor = field(default_factory=BandwidthMonitor)
    last_msg: Any = None
    last_msg_ts: float = 0.0
    callbacks: list[Callable[[Any], None]] = field(default_factory=list)
    _handle: Any = None  # rclpy Subscription
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_callback(self, cb: Callable[[Any], None]) -> None:
        """Register a per-message callback. Safe to call from any thread."""
        with self._lock:
            self.callbacks.append(cb)

    def remove_callback(self, cb: Callable[[Any], None]) -> bool:
        """Remove a previously registered callback. Returns True if found."""
        with self._lock:
            try:
                self.callbacks.remove(cb)
                return True
            except ValueError:
                return False

    def callback_count(self) -> int:
        with self._lock:
            return len(self.callbacks)

    def snapshot(self) -> tuple[Any, float]:
        """Return ``(last_msg, last_msg_ts)`` captured atomically."""
        with self._lock:
            return self.last_msg, self.last_msg_ts


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class RosBackend:
    """Thread-safe facade over rclpy.

    Use as a context manager::

        with RosBackend(node_name="rosight") as ros:
            ros.list_topics()
    """

    NODE_NAME_DEFAULT = "rosight"

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
                target=self._spin, name="rosight-ros-executor", daemon=True
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

    def set_domain_id(self, new_domain_id: int | None) -> None:
        """Restart the backend on a new ``ROS_DOMAIN_ID``.

        Tears down the current rclpy context (including every active
        subscription) and re-initializes against the new domain. Safe to
        call from a UI thread — serialized via the backend RLock.

        Raises ``RosUnavailable`` if rclpy isn't installed; the caller can
        catch and surface via ``app.notify``.
        """
        with self._lock:
            was_started = self._started
            if was_started:
                self.stop()
            self.domain_id = new_domain_id
            if was_started:
                self.start()

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
        from rosight.ros.introspection import get_message_class

        node = self._require_node()

        with self._lock:
            existing = self._subscriptions.get(topic)
            if existing is not None:
                if on_message:
                    existing.add_callback(on_message)
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
                with sub._lock:
                    sub.last_msg = msg
                    sub.last_msg_ts = ts
                    cbs = list(sub.callbacks)
                for cb in cbs:
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
            with sub._lock:
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
        from rosight.ros.introspection import get_message_class

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
        from rosight.ros.introspection import get_service_class

        node = self._require_node()
        srv_cls = get_service_class(type_name)
        client = node.create_client(srv_cls, service)
        try:
            if not client.wait_for_service(timeout_sec=timeout):
                raise TimeoutError(f"service {service!r} unavailable")
            future = client.call_async(request)
            # The executor already spins our node on its own thread; we
            # just need to block until the future completes or we time
            # out. ``concurrent.futures``-style ``result(timeout=...)`` is
            # available on rclpy's Future via the same name.
            try:
                return future.result(timeout=timeout)
            except TimeoutError:
                raise
            except Exception:
                # Some rclpy versions don't accept the ``timeout`` kwarg;
                # fall back to a watch loop with a wakeable Event.
                deadline = time.monotonic() + timeout
                done = threading.Event()
                future.add_done_callback(lambda _f: done.set())
                if not done.wait(timeout=max(0.0, deadline - time.monotonic())):
                    raise TimeoutError(f"service call to {service!r} timed out") from None
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

        pv = _build_param_value(PV(), value)
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


# ---------------------------------------------------------------------------
# rcl_interfaces.msg.ParameterValue (de)serialization
#
# A single table drives:
#   _param_type_name(t)  — int → human name
#   _param_value(pv)     — ParameterValue → Python value
#   _build_param_value(pv, value) — Python value → ParameterValue
#
# Type IDs come from rcl_interfaces/msg/ParameterType.msg and are stable
# across distros. Each row: (type_id, human_name, attr_name, container).
# ``container`` is ``None`` for scalars; for arrays it materializes the
# stored value into a list when reading.
# ---------------------------------------------------------------------------

_PARAM_TYPES: tuple[tuple[int, str, str | None, Any], ...] = (
    (0, "not_set", None, None),
    (1, "bool", "bool_value", None),
    (2, "integer", "integer_value", None),
    (3, "double", "double_value", None),
    (4, "string", "string_value", None),
    (5, "byte_array", "byte_array_value", list),
    (6, "bool_array", "bool_array_value", list),
    (7, "integer_array", "integer_array_value", list),
    (8, "double_array", "double_array_value", list),
    (9, "string_array", "string_array_value", list),
)


def _param_type_name(t: int) -> str:
    for type_id, name, _attr, _container in _PARAM_TYPES:
        if type_id == int(t):
            return name
    return "unknown"


def _param_value(v: Any) -> Any:
    t = int(v.type)
    for type_id, _name, attr, container in _PARAM_TYPES:
        if type_id != t:
            continue
        if attr is None:
            return None
        raw = getattr(v, attr)
        return container(raw) if container is not None else raw
    return None


def _build_param_value(pv: Any, value: Any) -> Any:
    """Populate an rcl_interfaces ParameterValue from a Python scalar.

    Only scalars are accepted today (bool/int/float/str); arrays would
    need an explicit element-type hint to disambiguate (``[1, 2]`` could
    be int or byte array). Order matters: ``bool`` must precede ``int``
    because ``isinstance(True, int)`` is True.
    """
    # (predicate, type_id, attr)
    rules: tuple[tuple[Callable[[Any], bool], int, str], ...] = (
        (lambda x: isinstance(x, bool), 1, "bool_value"),
        (lambda x: isinstance(x, int), 2, "integer_value"),
        (lambda x: isinstance(x, float), 3, "double_value"),
        (lambda x: isinstance(x, str), 4, "string_value"),
    )
    for pred, type_id, attr in rules:
        if pred(value):
            pv.type = type_id
            setattr(pv, attr, value)
            return pv
    raise TypeError(f"unsupported parameter type: {type(value).__name__}")
