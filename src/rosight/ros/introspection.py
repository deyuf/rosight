"""Message-type introspection helpers.

Goals:

* Look up a Python message class from a ``geometry_msgs/msg/Twist`` name.
* Walk a message recursively to produce ``(field_path, value, type)`` tuples
  for the tree view and field-picker (used by the plot panel).
* Provide a stub that handles plain dicts so unit tests can run without
  rclpy.
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

PRIMITIVE_TYPES = (bool, int, float, str, bytes)


@dataclass(frozen=True, slots=True)
class FieldEntry:
    path: str
    value: Any
    type_name: str
    is_numeric: bool
    is_array_numeric: bool = False

    @property
    def depth(self) -> int:
        return self.path.count(".") + self.path.count("[")


def get_message_class(type_name: str):
    """Resolve a ROS type string to its Python message class.

    Accepts ``pkg/msg/Type`` and ``pkg/Type`` forms.
    """
    parts = type_name.split("/")
    if len(parts) == 2:
        pkg, name = parts
        kind = "msg"
    elif len(parts) == 3:
        pkg, kind, name = parts
    else:
        raise ValueError(f"unsupported type name: {type_name!r}")

    # Try the rosidl_runtime_py helper first (handles all kinds gracefully).
    try:  # pragma: no cover — requires ROS
        from rosidl_runtime_py.utilities import get_message  # type: ignore

        if kind == "msg":
            return get_message(f"{pkg}/{kind}/{name}")
    except Exception:
        pass

    # Fallback: import ``pkg.msg`` (or .srv/.action) directly.
    module = importlib.import_module(f"{pkg}.{kind}")
    return getattr(module, name)


def get_service_class(type_name: str):
    """Resolve a service type string."""
    parts = type_name.split("/")
    if len(parts) == 2:
        pkg, name = parts
    elif len(parts) == 3 and parts[1] == "srv":
        pkg, _, name = parts
    else:
        raise ValueError(f"unsupported service type: {type_name!r}")
    module = importlib.import_module(f"{pkg}.srv")
    return getattr(module, name)


def get_action_class(type_name: str):
    """Resolve an action type string."""
    parts = type_name.split("/")
    if len(parts) == 2:
        pkg, name = parts
    elif len(parts) == 3 and parts[1] == "action":
        pkg, _, name = parts
    else:
        raise ValueError(f"unsupported action type: {type_name!r}")
    module = importlib.import_module(f"{pkg}.action")
    return getattr(module, name)


def iter_fields(
    msg: Any,
    _prefix: str = "",
    _depth: int = 0,
    _declared_type: str | None = None,
) -> Iterator[FieldEntry]:
    """Yield :class:`FieldEntry` for every leaf and container of ``msg``.

    Containers (nested messages, lists) are emitted as well so the tree view
    can display them. ``is_numeric`` is true for plottable scalar leaves;
    ``is_array_numeric`` is true for sequence/array containers whose element
    type is numeric (LaserScan ranges, JointState position, ...).
    """
    if _depth > 32:
        return  # safety: avoid pathological self-references

    # Primitive scalar
    if msg is None or isinstance(msg, PRIMITIVE_TYPES):
        if _prefix:
            yield FieldEntry(
                path=_prefix,
                value=msg,
                type_name=type(msg).__name__ if msg is not None else "None",
                is_numeric=isinstance(msg, (int, float, bool)),
            )
        return

    if isinstance(msg, dict):
        if _prefix:
            yield FieldEntry(_prefix, f"<{len(msg)} fields>", "dict", False)
        for k, v in msg.items():
            child = f"{_prefix}.{k}" if _prefix else k
            yield from iter_fields(v, child, _depth + 1)
        return

    if _is_array_like(msg):
        # ``msg`` may be a list, tuple, or array.array (rclpy uses the latter
        # for typed primitive sequences). Cap previewed elements at 64.
        try:
            length = len(msg)
        except TypeError:
            length = 0
        if _prefix:
            type_str = _declared_type or _array_type(msg)
            is_num_array = (
                _is_numeric_type(_declared_type)
                if _declared_type is not None
                else _runtime_array_is_numeric(msg)
            )
            yield FieldEntry(
                _prefix,
                f"<{length} items>",
                type_str,
                False,
                is_array_numeric=is_num_array,
            )
        for i, v in enumerate(_take(msg, 64)):
            child = f"{_prefix}[{i}]"
            yield from iter_fields(v, child, _depth + 1)
        if length > 64:
            yield FieldEntry(f"{_prefix}[...]", f"<+{length - 64} more>", "...", False)
        return

    # ROS message: prefer ``get_fields_and_field_types`` if present.
    fft = getattr(msg, "get_fields_and_field_types", None)
    if callable(fft):
        try:
            fields = fft()
        except Exception:
            fields = None
    else:
        fields = None

    if fields:
        if _prefix:
            yield FieldEntry(_prefix, _short_type(msg), _short_type(msg), False)
        for fname, ftype in fields.items():
            value = getattr(msg, fname, None)
            child = f"{_prefix}.{fname}" if _prefix else fname
            # Sequence types ("sequence<float32>", "float32[N]") are
            # primitive-per-element but at runtime arrive as lists/tuples;
            # walk them so the array container gets ``is_array_numeric``.
            if _is_sequence_type(ftype) and _is_array_like(value):
                yield from iter_fields(value, child, _depth + 1, _declared_type=ftype)
            elif _is_primitive_type(ftype):
                yield FieldEntry(
                    path=child,
                    value=value,
                    type_name=ftype,
                    is_numeric=_is_numeric_type(ftype),
                )
            else:
                yield from iter_fields(value, child, _depth + 1)
        return

    # Unknown object — fallback to vars().
    if _prefix:
        yield FieldEntry(_prefix, _short_type(msg), _short_type(msg), False)
    for k, v in vars(msg).items() if hasattr(msg, "__dict__") else []:
        child = f"{_prefix}.{k}" if _prefix else k
        yield from iter_fields(v, child, _depth + 1)


def _is_array_like(obj: Any) -> bool:
    """True for list, tuple, or array.array (rclpy typed primitive seqs).

    Excludes strings/bytes which would otherwise satisfy the iterable check.
    """
    import array as _array

    return isinstance(obj, (list, tuple, _array.array))


def _take(seq: Any, n: int) -> list[Any]:
    """Return at most ``n`` items from ``seq`` without copying the whole thing."""
    out: list[Any] = []
    for i, v in enumerate(seq):
        if i >= n:
            break
        out.append(v)
    return out


def _runtime_array_is_numeric(seq: Any) -> bool:
    """Heuristic for plain Python lists with no parent ROS metadata."""
    try:
        if not len(seq):
            return False
        first = next(iter(seq))
    except (TypeError, StopIteration):
        return False
    return isinstance(first, (int, float, bool)) and not isinstance(first, str)


def _is_numeric_sequence_type(ros_type: str) -> bool:
    """True for ``sequence<numeric>`` or ``numeric[]`` style declarations."""
    if "sequence<" in ros_type or "[" in ros_type:
        return _is_numeric_type(ros_type)
    return False


def _is_sequence_type(ros_type: str) -> bool:
    """True for any sequence/array declaration regardless of element type."""
    return "sequence<" in ros_type or "[" in ros_type


def _short_type(obj: Any) -> str:
    return type(obj).__module__.split(".")[0] + "/" + type(obj).__name__


def _array_type(seq: Any) -> str:
    if not seq:
        return "sequence"
    return f"sequence<{type(seq[0]).__name__}>"


_NUMERIC_TYPES = {
    "bool",
    "byte",
    "char",
    "int8",
    "uint8",
    "int16",
    "uint16",
    "int32",
    "uint32",
    "int64",
    "uint64",
    "float32",
    "float64",
}


def _is_primitive_type(ros_type: str) -> bool:
    base = ros_type.replace("sequence<", "").rstrip(">")
    base = base.split("[")[0]
    return base in _NUMERIC_TYPES or base in {"string", "wstring"}


def _is_numeric_type(ros_type: str) -> bool:
    base = ros_type.replace("sequence<", "").rstrip(">")
    base = base.split("[")[0]
    return base in _NUMERIC_TYPES
