"""Reusable widget that renders a ROS message as a navigable tree.

Used by the Topics panel (echo view) and the Plot panel field picker.
Emits ``MessageTree.FieldSelected`` when the user presses Enter on a numeric
leaf — nested inside the widget so Textual generates the handler name
``on_message_tree_field_selected`` for receivers.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual.binding import Binding
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

    @dataclass
    class SearchRequested(Message):
        """User pressed ``/`` in the tree; the host shows a search box."""

    BINDINGS = [
        ("p", "select_field", "Plot field"),
        ("enter", "activate", "Expand / plot"),
        ("slash", "search", "Search"),
        # Secondary keys stay out of the footer (it overflows narrow
        # terminals); they are listed in the ? help.
        Binding("n", "search_next", "Next match", show=False),
        Binding("N", "search_prev", "Prev match", show=False),
        ("y", "yank_path", "Copy path"),
        Binding("Y", "yank_value", "Copy value", show=False),
    ]

    # How long a changed value stays highlighted.
    FLASH_SECONDS = 0.6

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
        # path -> node for the tree currently shown, and the structural
        # signature it was built from. Used to update in place.
        self._nodes_by_path: dict[str, TreeNode[FieldEntry]] = {}
        self._signature: tuple[tuple[str, bool], ...] | None = None
        # path -> highlight deadline for values that just changed.
        self._flash: dict[str, float] = {}
        self._leaf_by_path: dict[str, bool] = {}
        self.search_query = ""
        # Counters exposed for tests / diagnostics.
        self.rebuilds = 0
        self.label_updates = 0

    def on_mount(self) -> None:
        self.set_interval(0.2, self._expire_flash)

    def update_message(self, msg: object) -> None:
        """Show the fields of ``msg``.

        Same message structure as last time (the normal case: the same
        topic ticking at a few Hz) → only labels whose value changed are
        rewritten; expanded/collapsed state, cursor and scroll stay exactly
        where the user left them.

        Different structure (another topic, or a variable-length array
        changed size) → rebuild, but re-apply the user's expanded set and
        put the cursor back on the same field path when it still exists.
        """
        self._last_msg = msg
        if msg is None:
            if self._signature is not None or self._nodes_by_path:
                self.clear()
                self._nodes_by_path = {}
                self._signature = None
            return
        entries = list(iter_fields(msg))
        leaves = _leaf_flags(entries)
        signature = tuple(zip((e.path for e in entries), leaves, strict=True))
        if signature == self._signature:
            self._update_in_place(entries, leaves)
        else:
            self._rebuild(entries, leaves)
            self._signature = signature

    def _update_in_place(self, entries: list[FieldEntry], leaves: list[bool]) -> None:
        nodes = self._nodes_by_path
        deadline = time.monotonic() + self.FLASH_SECONDS
        for entry, leaf in zip(entries, leaves, strict=True):
            node = nodes.get(entry.path)
            if node is None or node.data == entry:
                continue
            node.data = entry
            # Highlight changed leaf values so moving fields stand out.
            flash = leaf
            if flash:
                self._flash[entry.path] = deadline
            node.set_label(_format_label(entry, leaf, flash=flash))
            self.label_updates += 1

    def _expire_flash(self) -> None:
        if not self._flash:
            return
        now = time.monotonic()
        for path, until in list(self._flash.items()):
            if until > now:
                continue
            del self._flash[path]
            node = self._nodes_by_path.get(path)
            if node is not None and node.data is not None:
                node.set_label(_format_label(node.data, self._leaf_by_path.get(path, True)))

    def _rebuild(self, entries: list[FieldEntry], leaves: list[bool]) -> None:
        self.rebuilds += 1
        had_tree = bool(self._nodes_by_path)
        expanded = {p for p, n in self._nodes_by_path.items() if n.is_expanded}
        cursor = self.cursor_node
        cursor_path = cursor.data.path if cursor is not None and cursor.data else None

        self.clear()
        nodes: dict[str, TreeNode[FieldEntry]] = {}
        # Build a nested tree from the flat FieldEntry sequence using paths.
        node_stack: list[tuple[str, TreeNode[FieldEntry]]] = [("", self.root)]
        for entry, leaf in zip(entries, leaves, strict=True):
            parent_path = _parent_of(entry.path)
            while node_stack and not _is_ancestor(node_stack[-1][0], parent_path):
                node_stack.pop()
            parent_node = node_stack[-1][1] if node_stack else self.root
            label = _format_label(entry, leaf)
            if leaf:
                nodes[entry.path] = parent_node.add_leaf(label, data=entry)
            else:
                # First build: auto-expand the top levels. Later rebuilds:
                # honour what the user had open.
                expand = entry.path in expanded if had_tree else entry.depth < 2
                child = parent_node.add(label, data=entry, expand=expand)
                nodes[entry.path] = child
                node_stack.append((entry.path, child))
        self._nodes_by_path = nodes
        self._leaf_by_path = {e.path: leaf for e, leaf in zip(entries, leaves, strict=True)}
        self._flash.clear()

        target = nodes.get(cursor_path) if cursor_path else None
        if target is not None:
            # Line numbers are assigned on the next layout pass.
            self.call_after_refresh(self.move_cursor, target)

    # ----- search ------------------------------------------------------------

    def action_search(self) -> None:
        self.post_message(self.SearchRequested())

    def search(self, query: str, *, forward: bool = True, from_start: bool = False) -> bool:
        """Move the cursor to the next field whose path matches ``query``.

        Case-insensitive substring match on the full path (e.g. ``pos.x``
        doesn't match but ``position.x`` and ``x`` do). Wraps around.
        Collapsed ancestors of the match are expanded. Returns False when
        nothing matches.
        """
        self.search_query = query.strip()
        q = self.search_query.lower()
        if not q:
            return False
        paths = list(self._nodes_by_path)
        if not paths:
            return False
        cur = self.cursor_node
        cur_path = cur.data.path if cur is not None and cur.data is not None else None
        start = -1 if from_start or cur_path not in paths else paths.index(cur_path)
        n = len(paths)
        step = 1 if forward else -1
        for i in range(1, n + 1):
            path = paths[(start + step * i) % n]
            if q in path.lower():
                node = self._nodes_by_path[path]
                parent = node.parent
                while parent is not None:
                    parent.expand()
                    parent = parent.parent
                self.call_after_refresh(self.move_cursor, node)
                return True
        return False

    def action_search_next(self) -> None:
        self._search_step(forward=True)

    def action_search_prev(self) -> None:
        self._search_step(forward=False)

    def _search_step(self, *, forward: bool) -> None:
        if not self.search_query:
            self.action_search()
            return
        if not self.search(self.search_query, forward=forward):
            self.notify(f"no field matches {self.search_query!r}", severity="warning")

    # ----- copy -------------------------------------------------------------

    def action_yank_path(self) -> None:
        node = self.cursor_node
        if node is not None and node.data is not None:
            self._copy(node.data.path, "path")

    def action_yank_value(self) -> None:
        node = self.cursor_node
        if node is not None and node.data is not None:
            self._copy(format_value(node.data.value), "value")

    def _copy(self, text: str, what: str) -> None:
        # OSC 52: works over SSH and in most modern terminals.
        self.app.copy_to_clipboard(text)
        self.notify(f"copied {what}: {text}", timeout=2)

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
        if entry is None or (node.allow_expand and not entry.is_array_numeric):
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


def _leaf_flags(entries: list[FieldEntry]) -> list[bool]:
    """Leaf vs. container for each entry, decided by structure.

    ``iter_fields`` emits a container (nested message, array, dict) right
    before its children, with a *string* summary as its value
    ("geometry_msgs/Point", "<3 items>"). So the value type can't tell a
    container from a string leaf — whether the next entry lives under this
    path can. An empty container has no children and is shown as a leaf.
    """
    flags: list[bool] = []
    for i, entry in enumerate(entries):
        nxt = entries[i + 1].path if i + 1 < len(entries) else ""
        is_parent = nxt.startswith(entry.path + ".") or nxt.startswith(entry.path + "[")
        flags.append(not is_parent)
    return flags


def _format_label(entry: FieldEntry, leaf: bool, *, flash: bool = False) -> Text:
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
    elif leaf:
        text.append(format_value(entry.value), style="bold black on yellow" if flash else "cyan")
        text.append(f"  : {short_type(entry.type_name)}", style="dim")
    else:
        text.append(short_type(entry.type_name), style="dim")
    return text
