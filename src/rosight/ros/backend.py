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
from dataclasses import dataclass
from typing import Any

from rosight.ros import qos as qos_mod
from rosight.ros.discovery import EMPTY_SNAPSHOT, GraphMonitor, GraphSnapshot, next_snapshot
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


# Re-estimate the serialized size of *decoded* messages at most this often.
# Only used when raw subscriptions are unavailable; raw mode measures
# ``len(bytes)`` for free on every message.
_SIZE_ESTIMATE_PERIOD = 1.0


class Subscription:
    """Live subscription state shared between the rclpy executor and UI.

    Two ingestion modes:

    * **raw** (preferred, ``decode`` is set): rclpy hands us the serialized
      CDR ``bytes``. The executor thread only records the bytes, ticks the
      rate monitor and adds ``len(bytes)`` to the bandwidth monitor — no
      deserialization at all. The UI decodes lazily in :meth:`snapshot`,
      at most once per received message and only as often as it renders
      (4-15 Hz), regardless of how fast the topic publishes.
    * **decoded** (fallback): rclpy hands us message objects. Size is
      estimated by re-serializing, throttled to once per second.

    ``_lock`` guards the latest-message fields and the callback list; the
    executor never calls user code while holding it.
    """

    def __init__(
        self,
        topic: str,
        type_name: str,
        *,
        decode: Callable[[bytes], Any] | None = None,
    ) -> None:
        self.topic = topic
        self.type_name = type_name
        self.rate = RateMonitor()
        self.bandwidth = BandwidthMonitor()
        self.callbacks: list[Callable[[Any], None]] = []
        self._handle: Any = None  # rclpy Subscription
        self._lock = threading.Lock()
        self._decode = decode
        self._raw: bytes | None = None
        self._msg: Any = None
        self._ts = 0.0
        self._decoded_ts = 0.0
        self._size_est = 0
        self._size_est_ts = -1e9
        self.decode_errors = 0
        # Last incompatible-QoS report from rclpy, e.g. "RELIABILITY".
        self.qos_incompatible: str | None = None
        self.qos_incompatible_count = 0

    def __repr__(self) -> str:
        mode = "raw" if self.raw_mode else "decoded"
        return f"Subscription({self.topic!r}, {self.type_name!r}, {mode})"

    @property
    def raw_mode(self) -> bool:
        return self._decode is not None

    # ----- executor side ---------------------------------------------------

    def ingest_raw(self, data: bytes) -> None:
        """rclpy callback for ``raw=True`` subscriptions (executor thread)."""
        ts = time.monotonic()
        self.rate.tick(ts)
        self.bandwidth.tick(len(data), ts)
        with self._lock:
            self._raw = data
            self._ts = ts
            cbs = list(self.callbacks)
        if cbs:
            # Callbacks want message objects, so pay for one decode here —
            # and cache it so snapshot() doesn't decode the same bytes again.
            msg, _ = self.snapshot()
            self._dispatch(cbs, msg)

    def ingest_msg(self, msg: Any) -> None:
        """rclpy callback for decoded subscriptions (executor thread)."""
        ts = time.monotonic()
        self.rate.tick(ts)
        if ts - self._size_est_ts >= _SIZE_ESTIMATE_PERIOD:
            self._size_est = estimate_msg_size(msg)
            self._size_est_ts = ts
        self.bandwidth.tick(self._size_est, ts)
        self._set_latest(msg, ts)
        with self._lock:
            cbs = list(self.callbacks)
        if cbs:
            self._dispatch(cbs, msg)

    def _set_latest(self, msg: Any, ts: float) -> None:
        with self._lock:
            self._raw = None
            self._msg = msg
            self._ts = ts
            self._decoded_ts = ts

    @staticmethod
    def _dispatch(cbs: list[Callable[[Any], None]], msg: Any) -> None:
        for cb in cbs:
            try:
                cb(msg)
            except Exception:
                log.exception("subscriber callback raised")

    def on_incompatible_qos(self, info: Any) -> None:
        """rclpy ``incompatible_qos`` event handler (executor thread)."""
        policy = getattr(info, "last_policy_kind", None)
        name = getattr(policy, "name", None) or (str(policy) if policy is not None else "UNKNOWN")
        self.qos_incompatible = name.replace("RMW_QOS_POLICY_", "")
        self.qos_incompatible_count = int(
            getattr(info, "total_count", self.qos_incompatible_count + 1)
        )
        log.warning(
            "incompatible QoS on %s: %s (%d)",
            self.topic,
            self.qos_incompatible,
            self.qos_incompatible_count,
        )

    # ----- UI side ----------------------------------------------------------

    def snapshot(self) -> tuple[Any, float]:
        """Return ``(message, receive_ts)`` for the most recent message.

        In raw mode this decodes lazily (outside the lock) and caches the
        result, so repeated calls for the same message are free. On a
        decode failure the previous good message is returned.
        """
        with self._lock:
            raw, ts, msg, decoded_ts = self._raw, self._ts, self._msg, self._decoded_ts
        if raw is None or decoded_ts == ts or self._decode is None:
            return msg, (ts if raw is None or decoded_ts == ts else decoded_ts)
        try:
            decoded = self._decode(raw)
        except Exception:
            with self._lock:
                self.decode_errors += 1
            log.debug("decode failed on %s", self.topic, exc_info=True)
            return msg, decoded_ts
        with self._lock:
            if self._ts == ts:
                self._msg = decoded
                self._decoded_ts = ts
        return decoded, ts

    @property
    def last_msg(self) -> Any:
        return self.snapshot()[0]

    @property
    def last_msg_ts(self) -> float:
        with self._lock:
            return self._ts

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
        discovery_period: float = 1.0,
        shutdown_timeout: float = 2.0,
    ) -> None:
        self.node_name = node_name
        self.domain_id = domain_id
        self.default_depth = default_depth
        self.discovery_period = discovery_period
        self.shutdown_timeout = shutdown_timeout

        self._lock = threading.RLock()
        self._subscriptions: dict[str, Subscription] = {}
        self._started = False
        self._spin_thread: threading.Thread | None = None
        self._spin_error: str | None = None
        self._executor: Any = None
        self._node: Any = None
        self._rclpy: Any = None
        self._context: Any = None
        self._graph: GraphMonitor | None = None
        # Used when no GraphMonitor runs (tests drive a mock node directly).
        self._sync_snapshot: GraphSnapshot = EMPTY_SNAPSHOT
        # Injected at start() when rclpy provides them; tests may set these.
        self._deserialize_fn: Callable[[bytes, Any], Any] | None = None
        self._event_callbacks_cls: Any = None

    # ----- lifecycle -----------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            try:
                import rclpy
                from rclpy.executors import SingleThreadedExecutor
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

            self._deserialize_fn = _load_deserializer()
            self._event_callbacks_cls = _load_event_callbacks_cls()

            self._node = rclpy.create_node(self.node_name, context=self._context)
            # With raw subscriptions the executor callbacks only copy bytes
            # and tick counters, so one thread is plenty. Python's GIL means
            # a MultiThreadedExecutor added scheduling overhead without real
            # parallelism.
            self._executor = SingleThreadedExecutor(context=self._context)
            self._executor.add_node(self._node)
            self._spin_error = None
            self._spin_thread = threading.Thread(
                target=self._spin, name="rosight-ros-executor", daemon=True
            )
            self._spin_thread.start()
            self._started = True
            self._graph = GraphMonitor(self._collect_graph, self.discovery_period)
            self._graph.start()
            log.info("rclpy backend started as %s", self.node_name)

    def stop(self) -> None:
        """Tear everything down, bounded by ``shutdown_timeout``.

        Every blocking step (graph thread, executor shutdown, spin-thread
        join) has a timeout so quitting the TUI can never hang on a wedged
        DDS call.
        """
        with self._lock:
            if not self._started:
                return
            timeout = self.shutdown_timeout
            try:
                if self._graph is not None:
                    self._graph.stop(timeout)
                for sub in list(self._subscriptions.values()):
                    self._destroy_sub(sub)
                self._subscriptions.clear()
                if self._executor is not None:
                    try:
                        self._executor.shutdown(timeout_sec=timeout)
                    except TypeError:  # pragma: no cover — very old rclpy
                        self._executor.shutdown()
                    except Exception:
                        log.exception("executor shutdown failed")
                t = self._spin_thread
                if t is not None and t is not threading.current_thread():
                    t.join(timeout)
                    if t.is_alive():
                        log.warning("executor thread did not exit within %.1fs", timeout)
                if self._node is not None:
                    try:
                        self._node.destroy_node()
                    except Exception:
                        log.exception("destroy_node failed")
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
                self._graph = None
                self._sync_snapshot = EMPTY_SNAPSHOT
            log.info("rclpy backend stopped")

    def restart(self) -> None:
        """Stop and start again on the same domain (``:reconnect``)."""
        with self._lock:
            self.stop()
            self.start()

    @property
    def executor_alive(self) -> bool:
        """False when the backend is started but its spin thread has died."""
        if not self._started:
            return False
        t = self._spin_thread
        # No thread at all means a test/mock backend: treat as healthy.
        return t is None or t.is_alive()

    @property
    def last_error(self) -> str | None:
        return self._spin_error

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
        except Exception as e:
            self._spin_error = f"{type(e).__name__}: {e}"
            log.exception("executor stopped with error")

    # ----- discovery -----------------------------------------------------

    @property
    def started(self) -> bool:
        return self._started

    def _collect_graph(self) -> tuple[list[Any], list[Any], list[Any], list[Any]]:
        return self.list_topics(), self.list_nodes(), self.list_services(), self.list_actions()

    def graph_snapshot(self) -> GraphSnapshot:
        """Latest graph snapshot (O(1) when the background monitor runs).

        Without a monitor (mock/test backends) this collects synchronously,
        still bumping ``generation`` only when the content changed.
        """
        if not self._started:
            return EMPTY_SNAPSHOT
        graph = self._graph
        if graph is not None:
            return graph.latest
        with self._lock:
            self._sync_snapshot = next_snapshot(self._sync_snapshot, self._collect_graph)
            return self._sync_snapshot

    def request_graph_refresh(self) -> None:
        graph = self._graph
        if graph is not None:
            graph.request_refresh()

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
                type_name = self._resolve_topic_type(topic)
            msg_cls = get_message_class(type_name)

            # QoS auto-match
            if spec is None:
                spec = qos_mod.negotiate(self.publisher_qos(topic), self.default_depth)
            profile = qos_mod.to_rclpy(spec)

            deserialize = self._deserialize_fn
            decode = None
            if deserialize is not None:

                def decode(data: bytes, _cls: Any = msg_cls) -> Any:
                    return deserialize(data, _cls)

            sub = Subscription(topic=topic, type_name=type_name, decode=decode)
            if on_message:
                sub.callbacks.append(on_message)

            sub._handle = self._create_rclpy_subscription(node, msg_cls, topic, profile, sub)
            self._subscriptions[topic] = sub
            return sub

    def _resolve_topic_type(self, topic: str) -> str:
        snap = self.graph_snapshot()
        candidates = snap.topics if snap.generation else self.list_topics()
        ti = next((t for t in candidates if t.name == topic), None)
        if ti is None or not ti.types:
            raise ValueError(f"topic {topic!r} has no known type")
        return ti.primary_type

    def _create_rclpy_subscription(
        self, node: Any, msg_cls: Any, topic: str, profile: Any, sub: Subscription
    ) -> Any:
        """Create the rclpy subscription with the best options available.

        Tries, in order: raw bytes + QoS-event callbacks, raw only, decoded +
        QoS events, plain decoded. Each step drops a keyword that an older
        rclpy (or a test double) may not accept. If raw mode can't be used
        the Subscription is switched to decoded ingestion.
        """
        events = None
        if self._event_callbacks_cls is not None:
            try:
                events = self._event_callbacks_cls(incompatible_qos=sub.on_incompatible_qos)
            except Exception:
                log.debug("could not build SubscriptionEventCallbacks", exc_info=True)

        attempts: list[tuple[bool, Any]] = []
        for raw in (True, False) if sub.raw_mode else (False,):
            if events is not None:
                attempts.append((raw, events))
            attempts.append((raw, None))

        last_error: TypeError | None = None
        for raw, ev in attempts:
            kwargs: dict[str, Any] = {}
            if raw:
                kwargs["raw"] = True
            if ev is not None:
                kwargs["event_callbacks"] = ev
            callback = sub.ingest_raw if raw else sub.ingest_msg
            try:
                handle = node.create_subscription(msg_cls, topic, callback, profile, **kwargs)
            except TypeError as e:
                last_error = e
                continue
            if not raw:
                sub._decode = None
            return handle
        assert last_error is not None
        raise last_error

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
            # The executor spins our node on its own thread, so the response
            # completes the future there; we just block on an Event.
            # (rclpy's Future.result() takes no timeout argument.)
            done = threading.Event()
            future.add_done_callback(lambda _f: done.set())
            if not done.wait(timeout=timeout):
                try:
                    client.remove_pending_request(future)
                except Exception:
                    pass
                raise TimeoutError(f"service call to {service!r} timed out")
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


# ---------------------------------------------------------------------------
# Optional rclpy capabilities (resolved at start(); absent in tests)
# ---------------------------------------------------------------------------


def _load_deserializer() -> Callable[[bytes, Any], Any] | None:
    """``rclpy.serialization.deserialize_message`` if available.

    Enables raw-bytes subscriptions with lazy decoding.
    """
    try:
        from rclpy.serialization import deserialize_message  # type: ignore
    except Exception:  # pragma: no cover — env-dependent
        return None
    return deserialize_message  # type: ignore[no-any-return]


def _load_event_callbacks_cls() -> Any:
    """``SubscriptionEventCallbacks`` (moved between rclpy releases)."""
    for mod in ("rclpy.event_handler", "rclpy.qos_event"):
        try:
            module = __import__(mod, fromlist=["SubscriptionEventCallbacks"])
            return module.SubscriptionEventCallbacks
        except Exception:
            continue
    return None  # pragma: no cover — env-dependent
