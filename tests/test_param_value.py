"""Tests for the table-driven ParameterValue (de)serialization helpers.

These are pure-Python and don't require rcl_interfaces — we feed a tiny
duck-typed stub that exposes the same attribute names.
"""

from __future__ import annotations

import pytest

from rosight.ros.backend import _build_param_value, _param_type_name, _param_value


class _PV:
    """Stand-in for ``rcl_interfaces.msg.ParameterValue`` — same attrs."""

    __slots__ = (
        "bool_array_value",
        "bool_value",
        "byte_array_value",
        "double_array_value",
        "double_value",
        "integer_array_value",
        "integer_value",
        "string_array_value",
        "string_value",
        "type",
    )

    def __init__(self):
        self.type = 0
        self.bool_value = False
        self.integer_value = 0
        self.double_value = 0.0
        self.string_value = ""
        self.byte_array_value = []
        self.bool_array_value = []
        self.integer_array_value = []
        self.double_array_value = []
        self.string_array_value = []


@pytest.mark.parametrize(
    "type_id,name",
    [
        (0, "not_set"),
        (1, "bool"),
        (2, "integer"),
        (3, "double"),
        (4, "string"),
        (5, "byte_array"),
        (6, "bool_array"),
        (7, "integer_array"),
        (8, "double_array"),
        (9, "string_array"),
        (99, "unknown"),
    ],
)
def test_type_name_table(type_id, name):
    assert _param_type_name(type_id) == name


def test_unset_returns_none():
    pv = _PV()  # type 0
    assert _param_value(pv) is None


@pytest.mark.parametrize(
    "py_value,expected_type,expected_attr",
    [
        (True, 1, "bool_value"),
        (False, 1, "bool_value"),
        (42, 2, "integer_value"),
        (-7, 2, "integer_value"),
        (3.14, 3, "double_value"),
        ("hi", 4, "string_value"),
        ("", 4, "string_value"),
    ],
)
def test_build_param_value_scalars(py_value, expected_type, expected_attr):
    pv = _build_param_value(_PV(), py_value)
    assert pv.type == expected_type
    assert getattr(pv, expected_attr) == py_value


def test_build_param_value_bool_precedence_over_int():
    """``isinstance(True, int)`` is True — bool must match first."""
    pv = _build_param_value(_PV(), True)
    assert pv.type == 1
    assert pv.bool_value is True
    # The integer attr must stay at its default — not be set to 1 by
    # accident.
    assert pv.integer_value == 0


def test_build_param_value_rejects_unsupported():
    with pytest.raises(TypeError):
        _build_param_value(_PV(), [1, 2, 3])
    with pytest.raises(TypeError):
        _build_param_value(_PV(), None)


@pytest.mark.parametrize(
    "py_value",
    [True, False, 42, -7, 3.14, "hello", ""],
)
def test_scalar_roundtrip(py_value):
    """build_param_value → param_value should return the same scalar."""
    pv = _build_param_value(_PV(), py_value)
    assert _param_value(pv) == py_value


@pytest.mark.parametrize(
    "type_id,attr,raw",
    [
        (5, "byte_array_value", [b"\x01", b"\x02"]),
        (6, "bool_array_value", [True, False, True]),
        (7, "integer_array_value", [1, 2, 3]),
        (8, "double_array_value", [0.5, 1.5]),
        (9, "string_array_value", ["a", "b", "c"]),
    ],
)
def test_array_values_returned_as_list(type_id, attr, raw):
    pv = _PV()
    pv.type = type_id
    # array_array-like sources should be coerced to list.
    setattr(pv, attr, tuple(raw))
    out = _param_value(pv)
    assert out == list(raw)
    assert isinstance(out, list)


def test_unknown_type_returns_none():
    pv = _PV()
    pv.type = 99
    assert _param_value(pv) is None
