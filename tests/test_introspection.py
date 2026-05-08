from __future__ import annotations

import pytest

from lazyros.ros.introspection import (
    FieldEntry,
    _is_numeric_type,
    _is_primitive_type,
    iter_fields,
)


def test_iter_fields_walks_nested_message(tiny_message):
    entries = list(iter_fields(tiny_message))
    paths = {e.path for e in entries}
    assert "linear" in paths
    assert "linear.x" in paths
    assert "linear.y" in paths
    assert "angular.z" in paths


def test_iter_fields_marks_floats_as_numeric(tiny_message):
    leaves = {e.path: e for e in iter_fields(tiny_message) if isinstance(e.value, float)}
    assert leaves["linear.x"].is_numeric
    assert leaves["angular.z"].is_numeric


def test_iter_fields_handles_dicts():
    entries = list(iter_fields({"a": 1, "b": [10, 20]}))
    paths = {e.path for e in entries}
    assert "a" in paths
    assert "b" in paths
    assert "b[0]" in paths
    assert "b[1]" in paths


def test_iter_fields_truncates_long_arrays():
    big = list(range(200))
    entries = list(iter_fields({"x": big}))
    # 64 elements + 1 ellipsis marker + 1 container
    elems = [e for e in entries if e.path.startswith("x[") and e.path != "x[...]"]
    assert len(elems) == 64
    assert any(e.path == "x[...]" for e in entries)


def test_iter_fields_skips_top_level_when_no_prefix():
    out = list(iter_fields(5, ""))
    assert out == []  # no prefix means no leaf yielded for primitive root


def test_primitive_type_helpers():
    assert _is_primitive_type("float64")
    assert _is_primitive_type("string")
    assert _is_primitive_type("sequence<int32>")
    assert not _is_primitive_type("geometry_msgs/Vector3")
    assert _is_numeric_type("uint8")
    assert not _is_numeric_type("string")


def test_field_entry_immutable():
    e = FieldEntry(path="a", value=1, type_name="int", is_numeric=True)
    with pytest.raises(Exception):
        e.path = "b"  # type: ignore[misc]
