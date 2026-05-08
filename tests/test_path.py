from __future__ import annotations

import pytest

from lazyrosplus.utils.path import (
    format_path,
    get_value,
    is_numeric,
    parse_path,
)


def test_parse_simple_path():
    steps = parse_path("twist.linear.x")
    assert [s.name for s in steps] == ["twist", "linear", "x"]
    assert all(s.index is None for s in steps)


def test_parse_index_path():
    steps = parse_path("poses[2].position.x")
    assert steps[0].name == "poses"
    assert steps[1].index == 2
    assert steps[2].name == "position"


def test_parse_leading_slash():
    assert parse_path("/twist.linear.x") == parse_path("twist.linear.x")


def test_parse_invalid():
    with pytest.raises(ValueError):
        parse_path("twist@bad")
    with pytest.raises(ValueError):
        parse_path("twist[abc]")


def test_format_path_round_trip():
    p = "poses[1].orientation.w"
    assert format_path(parse_path(p)) == p


def test_get_value_dict():
    obj = {"a": {"b": [10, 20, 30]}}
    assert get_value(obj, "a.b[1]") == 20


def test_get_value_attr(tiny_message):
    assert get_value(tiny_message, "linear.x") == 1.0
    assert get_value(tiny_message, "angular.z") == 0.3


def test_get_value_missing_raises(tiny_message):
    with pytest.raises(KeyError):
        get_value(tiny_message, "linear.q")


def test_is_numeric():
    assert is_numeric(1)
    assert is_numeric(1.5)
    assert is_numeric(True)
    assert not is_numeric("1.0")
    assert not is_numeric([1, 2])
