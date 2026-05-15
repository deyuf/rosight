"""Reusable widget that renders a ROS message as a navigable tree.

Used by the Topics panel (echo view) and the Plot panel field picker.
Emits ``MessageTree.FieldSelected`` when the user presses Enter on a numeric
leaf — nested inside the widget so Textual generates the handler name
``on_message_tree_field_selected`` for receivers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual.message import Message
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from rosight.ros.introspection import FieldEntry, iter_fields
from rosight.utils.formatting import format_value, short_type


class MessageTree(Tree[FieldEntry]):
    """A Tree[FieldEntry] view of a single ROS message snapshot."""

    @dataclass
    class FieldSelected(Message):
        """Posted when the user picks a field path."""

        path: str
        value: object
        type_name: str
        is_numeric: bool
        kind: Literal["scalar", "array"] = "scalar"

    BINDINGS = [
        ("p", "select_field", "Plot field"),
        ("enter", "activate", "Expand / plot"),
    ]

    DEFAULT_CSS = """
    MessageTree {
        background: $panel;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(label="message", **kwargs)
        self.show_root = False
        self.guide_depth = 2
        self._last_msg: object | None = None

    def update_message(self, msg: object) -> None:
        """Replace the tree contents with fields of ``msg``."""
        self._last_msg = msg
        self.clear()
        if msg is None:
            return
        # Build a lightweight nested tree from FieldEntry sequence using path depth.
        node_stack: list[tuple[str, TreeNode]] = [("", self.root)]
        for entry in iter_fields(msg):
            # determine parent path
            parent_path = _parent_of(entry.path)
            while node_stack and not _is_ancestor(node_stack[-1][0], parent_path):
                node_stack.pop()
            parent_node = node_stack[-1][1] if node_stack else self.root
            label = _format_label(entry)
            if _is_leaf(entry):
                parent_node.add_leaf(label, data=entry)
            else:
                child = parent_node.add(label, data=entry, expand=entry.depth < 2)
                node_stack.append((entry.path, child))

    def action_select_field(self) -> None:
        node = self.cursor_node
        if node is None or node.data is None:
            return
        entry: FieldEntry = node.data
        kind: Literal["scalar", "array"] = "array" if entry.is_array_numeric else "scalar"
        self.post_message(
            MessageTree.FieldSelected(
                path=entry.path,
                value=entry.value,
                type_name=entry.type_name,
                is_numeric=entry.is_numeric,
                kind=kind,
            )
        )

    def action_activate(self) -> None:
        """Enter handler that does the right thing for the node under cursor.

        - Sub-message / non-plottable array node → toggle expand/collapse.
        - Numeric leaf → post ``FieldSelected`` (scalar plot).
        - Numeric array container → post ``FieldSelected`` (snapshot plot).
        """
        node = self.cursor_node
        if node is None:
            return
        entry: FieldEntry | None = node.data
        if entry is None or (not _is_leaf(entry) and not entry.is_array_numeric):
            # Non-leaf and not a plottable array: behave like base Tree's default.
            node.toggle()
            return
        self.action_select_field()


def _parent_of(path: str) -> str:
    if "." not in path and "[" not in path:
        return ""
    if path.endswith("]"):
        # strip trailing [N]
        return path.rsplit("[", 1)[0]
    return path.rsplit(".", 1)[0]


def _is_ancestor(candidate: str, target: str) -> bool:
    if candidate == target:
        return True
    if not candidate:
        return True
    return target.startswith(candidate + ".") or target.startswith(candidate + "[")


def _is_leaf(entry: FieldEntry) -> bool:
    return isinstance(entry.value, (int, float, bool, str, bytes)) or entry.value is None


def _format_label(entry: FieldEntry) -> Text:
    name = entry.path.rsplit(".", 1)[-1].rsplit("[", 1)[-1]
    if "[" in entry.path.split(".")[-1]:
        # array element: keep the index visible
        name = entry.path.split(".")[-1]
    text = Text()
    text.append(name, style="bold")
    text.append("  ")
    if entry.is_array_numeric and isinstance(entry.value, str) and entry.value.startswith("<"):
        # Numeric-array container: emphasize that it's snapshot-plottable.
        text.append(entry.value, style="dim italic")
        text.append("  ")
        text.append("[plot ↵]", style="green bold")
        text.append(f"  : {short_type(entry.type_name)}", style="dim")
    elif isinstance(entry.value, str) and entry.value.startswith("<"):
        text.append(entry.value, style="dim italic")
    elif _is_leaf(entry):
        text.append(format_value(entry.value), style="cyan")
        text.append(f"  : {short_type(entry.type_name)}", style="dim")
    else:
        text.append(short_type(entry.type_name), style="dim")
    return text
