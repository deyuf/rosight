"""Tests for the plot color picker.

Regression: ``assign_color(len(series))`` would collide after deleting
an earlier series. ``pick_color`` returns the first palette entry not
currently in use, which keeps all visible series distinct as long as
fewer than ``len(_PALETTE)`` are active.
"""

from __future__ import annotations

from rosight.widgets.plot_view import _PALETTE, assign_color, pick_color


def test_pick_color_avoids_used():
    used = {_PALETTE[0], _PALETTE[1]}
    c = pick_color(used)
    assert c == _PALETTE[2]


def test_pick_color_empty_picks_first():
    assert pick_color(set()) == _PALETTE[0]


def test_no_collisions_below_palette_size():
    """Allocating N < len(_PALETTE) colors yields N distinct colors."""
    used: set[str] = set()
    picks: list[str] = []
    for _ in range(len(_PALETTE)):
        c = pick_color(used)
        picks.append(c)
        used.add(c)
    assert len(set(picks)) == len(_PALETTE)


def test_palette_exhausted_falls_back_round_robin():
    """Beyond palette size we accept collisions but must never crash."""
    used = set(_PALETTE)  # everything taken
    c = pick_color(used)
    assert c in _PALETTE


def test_collision_after_delete_then_add():
    """The regression case: take colors 0/1/2, free color 1, ask for a
    new color. The old ``assign_color(len(series))`` would have given
    color 3 (no collision yet), but after enough churn it'd hand back a
    color still in use. ``pick_color`` always returns the freed slot."""
    # Series 0/1/2 take palette[0..2]
    used = {_PALETTE[0], _PALETTE[1], _PALETTE[2]}
    # Delete series 1 — _PALETTE[1] becomes free again
    used.discard(_PALETTE[1])
    c = pick_color(used)
    assert c == _PALETTE[1]


def test_assign_color_back_compat_still_works():
    """``assign_color`` is kept for back-compat with any external caller."""
    assert assign_color(0) == _PALETTE[0]
    assert assign_color(len(_PALETTE)) == _PALETTE[0]  # round-robin


def test_simulated_add_remove_keeps_live_colors_distinct():
    """Simulate the PlotView allocation flow without instantiating the
    Textual widget (which needs an App). The series dict holds whatever
    ``pick_color`` returned, and the next allocation passes the current
    set in."""
    series: dict[str, str] = {}

    def add(label: str) -> str:
        c = pick_color(set(series.values()))
        series[label] = c
        return c

    def remove(label: str) -> None:
        series.pop(label, None)

    c0 = add("a")
    c1 = add("b")
    c2 = add("c")
    assert len({c0, c1, c2}) == 3

    remove("b")
    c3 = add("d")
    # Live series colors stay distinct…
    assert len(set(series.values())) == len(series)
    # …and the freshly-freed slot is the first candidate.
    assert c3 == c1
