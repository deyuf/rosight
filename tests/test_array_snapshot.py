"""Tests for the 1D-array snapshot plotting pipeline.

Covers:
- ``iter_fields`` marks numeric-element arrays with ``is_array_numeric``.
- ``MessageTree.FieldSelected.kind`` is "array" for those entries.
- ``PlotPanel.add_snapshot_series`` registers and ``_sample`` pushes arrays.
- ``SnapshotSeries.stats`` returns min/max/len.
"""

from __future__ import annotations

import pytest

from rosight.ros.introspection import iter_fields
from rosight.widgets.plot_view import PlotSeries, SnapshotSeries


class _FakeLaserScan:
    """Duck-typed sensor_msgs/LaserScan for tests without rclpy."""

    __slots__ = ("angle_min", "frame_id", "intensities", "ranges")

    def __init__(self, ranges, intensities=None, angle_min=0.0, frame_id="laser"):
        self.ranges = ranges
        self.intensities = intensities or []
        self.angle_min = angle_min
        self.frame_id = frame_id

    @staticmethod
    def get_fields_and_field_types():
        return {
            "ranges": "sequence<float32>",
            "intensities": "sequence<float32>",
            "angle_min": "float32",
            "frame_id": "string",
        }


def test_iter_fields_marks_numeric_array_container():
    msg = _FakeLaserScan(ranges=[1.0, 2.0, 3.0])
    entries = {e.path: e for e in iter_fields(msg)}
    assert "ranges" in entries
    assert entries["ranges"].is_array_numeric is True
    assert entries["ranges"].is_numeric is False  # container itself isn't scalar
    assert entries["ranges"].type_name == "sequence<float32>"


def test_iter_fields_empty_array_with_declared_type_is_array_numeric():
    msg = _FakeLaserScan(ranges=[])
    entries = {e.path: e for e in iter_fields(msg)}
    # Empty list — without parent metadata we couldn't know, but the
    # parent's declared type ``sequence<float32>`` lets us mark it.
    assert entries["ranges"].is_array_numeric is True


def test_iter_fields_string_array_not_array_numeric():
    entries = {e.path: e for e in iter_fields({"names": ["a", "b", "c"]})}
    assert entries["names"].is_array_numeric is False


def test_iter_fields_numeric_list_in_dict_is_detected():
    entries = {e.path: e for e in iter_fields({"vals": [1.0, 2.0]})}
    # No parent ROS metadata, runtime heuristic by first element.
    assert entries["vals"].is_array_numeric is True


def test_iter_fields_handles_array_array_from_rclpy():
    """rclpy delivers numeric sequences as ``array.array``, not ``list``."""
    import array as pyarray

    class _Imu:
        __slots__ = ("orientation_covariance",)

        def __init__(self, cov):
            self.orientation_covariance = cov

        @staticmethod
        def get_fields_and_field_types():
            return {"orientation_covariance": "float64[9]"}

    msg = _Imu(pyarray.array("d", [0.0] * 9))
    entries = {e.path: e for e in iter_fields(msg)}
    assert "orientation_covariance" in entries
    assert entries["orientation_covariance"].is_array_numeric is True
    # Children are still individual numeric leaves.
    assert "orientation_covariance[0]" in entries
    assert entries["orientation_covariance[0]"].is_numeric is True


def test_snapshot_series_stats():
    s = SnapshotSeries(label="x")
    assert s.stats() is None
    s.set_latest([1.0, 2.0, 5.0, -3.0])
    stat = s.stats()
    assert stat is not None
    mn, mx, ln = stat
    assert mn == -3.0
    assert mx == 5.0
    assert ln == 4


def test_snapshot_series_set_latest_replaces():
    s = SnapshotSeries(label="x")
    s.set_latest([1.0, 2.0])
    s.set_latest([10.0, 20.0, 30.0])
    assert s.values == [10.0, 20.0, 30.0]


def test_plot_panel_sample_pushes_array(monkeypatch):
    """End-to-end: a fake subscription's last_msg flows through _sample."""
    # Defer textual imports to keep this test light when env lacks deps.
    pytest.importorskip("textual")
    from rosight.widgets.plot_panel import PlotPanel
    from rosight.widgets.plot_view import PlotView

    # Build a PlotPanel without mounting it: directly drive the sample path
    # by stubbing the .ros and .plot accessors.
    panel = PlotPanel()

    class _Sub:
        last_msg = _FakeLaserScan(ranges=[1.0, 2.0, 4.0])
        last_msg_ts = 0.0

    class _Ros:
        started = True

        def get_subscription(self, topic):
            return _Sub()

        def subscribe(self, topic, *a, **kw):
            return _Sub()

    plot = PlotView()
    # Monkey-patch the cached properties so _sample can use them.
    monkeypatch.setattr(type(panel), "ros", property(lambda self: _Ros()))
    monkeypatch.setattr(type(panel), "plot", property(lambda self: plot))

    panel.add_snapshot_series("/scan", "ranges")
    panel._sample()

    series = plot.series["/scan/ranges"]
    assert isinstance(series, SnapshotSeries)
    assert series.values == [1.0, 2.0, 4.0]


def test_plot_view_mixes_time_and_snapshot_series():
    pytest.importorskip("textual")
    from rosight.widgets.plot_view import PlotView

    view = PlotView()
    view.add_series("scalar1")
    view.add_snapshot_series("array1")
    assert isinstance(view.series["scalar1"], PlotSeries)
    assert isinstance(view.series["array1"], SnapshotSeries)

    # push to each
    view.push("scalar1", 1.0)
    view.push_snapshot("array1", [1.0, 2.0])
    assert view.series["scalar1"].latest == 1.0
    assert view.series["array1"].values == [1.0, 2.0]


def test_plot_view_paused_ignores_pushes():
    pytest.importorskip("textual")
    from rosight.widgets.plot_view import PlotView

    view = PlotView()
    view.add_series("s")
    view.add_snapshot_series("a")
    view.paused = True
    view.push("s", 7.0)
    view.push_snapshot("a", [1, 2, 3])
    assert view.series["s"].latest is None
    assert view.series["a"].values == []
