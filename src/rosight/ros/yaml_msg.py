"""Convert ROS messages to and from YAML (the ``ros2 topic pub`` format).

Used by the publish / service-call / action-goal / parameter forms: the
form is a YAML document pre-filled from the message definition (or from
the last received message), the user edits it, and we build the request
object back from it.

``rosidl_runtime_py`` is used for YAML → message when available (it knows
every ROS field type, including arrays of nested messages). The pure
Python fallback covers primitives, nested messages and primitive arrays,
which is what tests and simple messages need.
"""

from __future__ import annotations

import array
from typing import Any

import yaml


class MessageYamlError(ValueError):
    """The YAML text can't be turned into the requested message."""


def to_plain(value: Any, _depth: int = 0) -> Any:
    """Recursively convert a message (or field value) to plain Python."""
    if _depth > 32:
        return None
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (bytes, bytearray)):
        return list(value)
    if isinstance(value, array.array):
        return value.tolist()
    tolist = getattr(value, "tolist", None)  # numpy arrays / scalars
    if callable(tolist) and not hasattr(value, "get_fields_and_field_types"):
        return tolist()
    if isinstance(value, (list, tuple)):
        return [to_plain(v, _depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: to_plain(v, _depth + 1) for k, v in value.items()}
    fields = getattr(value, "get_fields_and_field_types", None)
    if callable(fields):
        return {name: to_plain(getattr(value, name, None), _depth + 1) for name in fields()}
    return str(value)


def message_to_yaml(msg: Any) -> str:
    """YAML text for ``msg`` (field order preserved)."""
    plain = to_plain(msg)
    if plain == {}:
        return "{}\n"
    return yaml.safe_dump(plain, sort_keys=False, default_flow_style=False, allow_unicode=True)


def parse_yaml(text: str) -> Any:
    try:
        return yaml.safe_load(text) if text.strip() else {}
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        raise MessageYamlError(f"invalid YAML{where}: {getattr(e, 'problem', e)}") from e


def yaml_to_message(text: str, msg_cls: Any) -> Any:
    """Build a ``msg_cls`` instance from YAML text.

    Raises :class:`MessageYamlError` with a readable reason on bad YAML,
    unknown fields or values of the wrong type.
    """
    data = parse_yaml(text)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise MessageYamlError("expected a mapping of field: value at the top level")
    msg = msg_cls()
    try:
        from rosidl_runtime_py.set_message import set_message_fields  # type: ignore
    except Exception:
        set_message_fields = None
    try:
        if set_message_fields is not None:
            set_message_fields(msg, data)
        else:
            _set_fields(msg, data, "")
    except MessageYamlError:
        raise
    except Exception as e:
        raise MessageYamlError(str(e)) from e
    return msg


def _set_fields(obj: Any, data: dict[str, Any], prefix: str) -> None:
    fields_fn = getattr(obj, "get_fields_and_field_types", None)
    known = fields_fn() if callable(fields_fn) else {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if key not in known:
            raise MessageYamlError(f"unknown field {path!r}")
        current = getattr(obj, key)
        if isinstance(value, dict):
            if not callable(getattr(current, "get_fields_and_field_types", None)):
                raise MessageYamlError(f"{path!r} is not a nested message")
            _set_fields(current, value, f"{path}.")
            continue
        setattr(obj, key, _coerce(value, current, path))


def _coerce(value: Any, current: Any, path: str) -> Any:
    """Match ``value`` to the type of the field's current (default) value."""
    if callable(getattr(current, "get_fields_and_field_types", None)):
        raise MessageYamlError(f"{path!r} is a nested message; expected a mapping, got {value!r}")
    if isinstance(current, bool):
        if not isinstance(value, bool):
            raise MessageYamlError(f"{path!r} expects true/false, got {value!r}")
        return value
    if isinstance(current, float):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise MessageYamlError(f"{path!r} expects a number, got {value!r}")
        return float(value)
    if isinstance(current, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise MessageYamlError(f"{path!r} expects an integer, got {value!r}")
        return value
    if isinstance(current, str):
        if not isinstance(value, str):
            raise MessageYamlError(f"{path!r} expects a string, got {value!r}")
        return value
    if isinstance(current, (list, tuple, array.array)) and not isinstance(value, list):
        raise MessageYamlError(f"{path!r} expects a list, got {value!r}")
    return value
