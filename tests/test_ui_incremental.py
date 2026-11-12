"""Incremental UI updates: DataTable sync, MessageTree in-place updates,
fuzzy filter and sparkline helpers."""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import DataTable

from rosight.utils.datatable import current_row_key, sync_table
from rosight.utils.formatting import sparkline
from rosight.utils.fuzzy import matches
from rosight.widgets.message_tree import MessageTree

# ----- fuzzy / sparkline -----------------------------------------------------


@pytest.mark.parametrize(
    ("query", "fields", "expected"),
    [
        ("", ("/odom",), True),
        ("odom", ("/odom",), True),
        ("odm", ("/odom",), True),  # subsequence
        ("ODM", ("/odom",), True),  # case-insensitive
        ("mdo", ("/odom",), False),  # order matters
        ("scan laser", ("/scan", "sensor_msgs/msg/LaserScan"), True),
        ("scan imu", ("/scan", "sensor_msgs/msg/LaserScan"), False),
        ("twist", ("/cmd_vel", ""), False),
    ],
)
def test_fuzzy_matches(query, fields, expected):
    assert matches(query, *fields) is expected


def test_sparkline_shapes():
    assert sparkline([]) == ""
    assert sparkline([0, 0, 0]) == "▁▁▁"
    assert sparkline([10, 10]) == "▅▅", "steady rate → flat mid line, not a bar"
    assert sparkline([50.0, 49.9, 50.1]) == "▅▅▅"
    assert sparkline([10, 10, 3, 10])[2] == "▁", "a drop is visible"
    line = sparkline([0, 5, 10])
    assert line[0] == "▁" and line[-1] == "█" and len(line) == 3
    assert len(sparkline(list(range(50)), width=12)) == 12


# ----- sync_table ------------------------------------------------------------


class _TableApp(App):
    def compose(self) -> ComposeResult:
        yield DataTable(id="t", cursor_type="row")

    def on_mount(self) -> None:
        self.query_one(DataTable).add_columns("Name", "Hz")


def _rows(*pairs):
    return [(k, (k, hz)) for k, hz in pairs]


@pytest.mark.asyncio
async def test_sync_table_updates_cells_in_place():
    async with _TableApp().run_test(size=(60, 20)) as pilot:
        t = pilot.app.query_one(DataTable)
        assert sync_table(t, _rows(("a", "1.0"), ("b", "2.0"), ("c", "3.0"))) is True
        t.move_cursor(row=2, animate=False)
        await pilot.pause()

        calls = []
        orig_clear = t.clear
        t.clear = lambda *a, **kw: (calls.append("clear"), orig_clear(*a, **kw))[1]

        # Same keys, one value changed with the same width → no rebuild.
        changed = sync_table(t, _rows(("a", "1.0"), ("b", "2.5"), ("c", "3.0")))
        await pilot.pause()
        assert calls == []
        assert changed is False
        assert t.get_cell("b", list(t.columns)[1]) == "2.5"
        assert current_row_key(t) == "c", "cursor must not move on an in-place update"

        # Unchanged rows → nothing to do at all.
        assert sync_table(t, _rows(("a", "1.0"), ("b", "2.5"), ("c", "3.0"))) is False

        # Width change is reported so the caller can refit columns.
        assert sync_table(t, _rows(("a", "1.0"), ("b", "12.5"), ("c", "3.0"))) is True
        assert calls == []


@pytest.mark.asyncio
async def test_sync_table_rebuild_keeps_cursor_on_same_key():
    async with _TableApp().run_test(size=(60, 20)) as pilot:
        t = pilot.app.query_one(DataTable)
        sync_table(t, _rows(("a", "1"), ("b", "2"), ("c", "3")))
        t.move_cursor(row=1, animate=False)  # on "b"
        await pilot.pause()
        # A new topic appears *before* b → rows shift, cursor must follow b.
        assert sync_table(t, _rows(("a", "1"), ("a2", "9"), ("b", "2"), ("c", "3"))) is True
        await pilot.pause()
        assert current_row_key(t) == "b"
        # b disappears → no crash, table shrinks.
        sync_table(t, _rows(("a", "1"), ("c", "3")))
        await pilot.pause()
        assert t.row_count == 2


@pytest.mark.asyncio
async def test_sync_table_compares_rich_text_cells():
    async with _TableApp().run_test(size=(60, 20)) as pilot:
        t = pilot.app.query_one(DataTable)
        sync_table(t, [("a", (Text("a", style="bold"), "1"))])
        assert sync_table(t, [("a", (Text("a", style="bold"), "1"))]) is False


# ----- MessageTree -----------------------------------------------------------


class _Vec:
    def __init__(self, x, y):
        self.x, self.y = x, y

    @staticmethod
    def get_fields_and_field_types():
        return {"x": "float64", "y": "float64"}


class _Pose:
    def __init__(self, x=0.0, y=0.0, ranges=(1.0, 2.0)):
        self.position = _Vec(x, y)
        self.orientation = _Vec(0.0, 1.0)
        self.ranges = list(ranges)

    @staticmethod
    def get_fields_and_field_types():
        return {
            "position": "geometry_msgs/Point",
            "orientation": "geometry_msgs/Point",
            "ranges": "sequence<float32>",
        }


class _TreeApp(App):
    def compose(self) -> ComposeResult:
        yield MessageTree(id="tree")


@pytest.mark.asyncio
async def test_message_tree_updates_labels_in_place():
    async with _TreeApp().run_test(size=(80, 30)) as pilot:
        tree = pilot.app.query_one(MessageTree)
        tree.update_message(_Pose(1.0, 2.0))
        await pilot.pause()
        assert tree.rebuilds == 1
        node_x = tree._nodes_by_path["position.x"]

        tree.update_message(_Pose(1.5, 2.0))
        await pilot.pause()
        assert tree.rebuilds == 1, "same structure must not rebuild"
        assert tree._nodes_by_path["position.x"] is node_x, "node identity preserved"
        assert "1.5" in str(node_x.label)
        assert tree.label_updates == 1, "only the changed field is relabelled"


@pytest.mark.asyncio
async def test_message_tree_preserves_user_collapse_and_cursor_on_rebuild():
    async with _TreeApp().run_test(size=(80, 30)) as pilot:
        tree = pilot.app.query_one(MessageTree)
        tree.update_message(_Pose())
        await pilot.pause()
        # User collapses "position" and puts the cursor on orientation.y.
        tree._nodes_by_path["position"].collapse()
        await pilot.pause()
        tree.move_cursor(tree._nodes_by_path["orientation.y"])
        await pilot.pause()

        # Array length change → structural rebuild.
        tree.update_message(_Pose(ranges=(1.0, 2.0, 3.0)))
        await pilot.pause()
        await pilot.pause()
        assert tree.rebuilds == 2
        assert not tree._nodes_by_path["position"].is_expanded
        assert tree._nodes_by_path["orientation"].is_expanded
        assert tree.cursor_node is tree._nodes_by_path["orientation.y"]


@pytest.mark.asyncio
async def test_message_tree_none_clears():
    async with _TreeApp().run_test(size=(80, 30)) as pilot:
        tree = pilot.app.query_one(MessageTree)
        tree.update_message(_Pose())
        tree.update_message(None)
        await pilot.pause()
        assert tree._nodes_by_path == {}
        tree.update_message(_Pose())
        assert tree.rebuilds == 2


@pytest.mark.asyncio
async def test_message_tree_nests_submessages():
    """Regression: containers carry a *string* summary value, which the old
    value-based leaf check mistook for a leaf — the whole tree was flat and
    ``position.x`` / ``orientation.x`` showed up as sibling ``x`` rows."""
    async with _TreeApp().run_test(size=(80, 30)) as pilot:
        tree = pilot.app.query_one(MessageTree)
        tree.update_message(_Pose())
        await pilot.pause()
        position = tree._nodes_by_path["position"]
        assert position.allow_expand
        assert tree._nodes_by_path["position.x"].parent is position
        assert tree._nodes_by_path["orientation.x"].parent is tree._nodes_by_path["orientation"]
        assert not tree._nodes_by_path["position.x"].allow_expand
        # Top level of the root holds only the three top-level fields.
        assert [str(c.data.path) for c in tree.root.children] == [
            "position",
            "orientation",
            "ranges",
        ]


def test_ellipsize_middle_keeps_both_ends():
    from rosight.utils.datatable import ellipsize_middle

    name = "rcl_interfaces/msg/ParameterEventDescriptors"
    short = ellipsize_middle(name, 30)
    assert len(short) == 30 and "…" in short
    assert short.startswith("rcl_interfaces") and short.endswith("Descriptors")
    assert ellipsize_middle("short", 30) == "short"


@pytest.mark.asyncio
async def test_sync_table_shrinks_column_when_cells_get_narrower():
    async with _TableApp().run_test(size=(60, 20)) as pilot:
        t = pilot.app.query_one(DataTable)
        sync_table(t, _rows(("a", "a-very-long-value-indeed"), ("b", "2")))
        await pilot.pause()
        wide = t.virtual_size.width
        sync_table(t, _rows(("a", "short"), ("b", "2")))  # same keys
        await pilot.pause()
        assert t.virtual_size.width < wide
