"""Layout guard: every view must fit small (100x30) and default (150x42)
terminals without horizontal scrolling in its tables / trees.

Runs the documentation-screenshot scenes (scripts/generate_screenshots.py)
against the demo backend and, instead of saving images, checks each view.
This caught the Topics table overflowing half a terminal, empty-state
placeholders permanently widening columns, and the Bags table being fitted
before it had rows.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("textual")
pytest.importorskip("plotext")

from textual.widgets import DataTable, Tree

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [(100, 30), (150, 42)])
async def test_all_views_fit_without_horizontal_scrolling(size, monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    sys.modules.pop("generate_screenshots", None)
    import generate_screenshots as shots

    problems: list[str] = []
    visited: list[str] = []

    def check(app, name):
        visited.append(name)
        for w in app.screen.query("*"):
            if not isinstance(w, DataTable | Tree) or not w.display or not w.region.width:
                continue
            if w.show_horizontal_scrollbar:
                problems.append(
                    f"{name}: {w!r} needs {w.virtual_size.width} cells, "
                    f"has {w.scrollable_content_region.width}"
                )

    from rosight.ros import introspection

    originals = (introspection.get_message_class, introspection.get_service_class)
    monkeypatch.setattr(shots, "save", check)
    monkeypatch.setattr(shots, "OUT", tmp_path)
    await shots.capture_all(size)
    # The demo type lookup must not leak into later tests (it broke the
    # real-rclpy tests in CI when it did).
    assert (introspection.get_message_class, introspection.get_service_class) == originals
    assert len(visited) == len(shots.SCENES)
    assert not problems, "\n".join(problems)
