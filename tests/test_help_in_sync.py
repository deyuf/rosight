"""The help overlay must list every key the panels actually bind.

The old help advertised keys that did nothing (params s/y, plot p, h/b)
and missed real ones. This test fails as soon as a binding is added
without documenting it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.binding import Binding

from rosight.app import RosightApp
from rosight.widgets.actions_panel import ActionsPanel
from rosight.widgets.bags_panel import BagsPanel
from rosight.widgets.help_screen import HELP_TEXT
from rosight.widgets.image_screen import ImagePreviewScreen
from rosight.widgets.interfaces_panel import InterfacesPanel
from rosight.widgets.message_tree import MessageTree
from rosight.widgets.nodes_panel import NodesPanel
from rosight.widgets.params_panel import ParamsPanel
from rosight.widgets.plot_panel import PlotPanel
from rosight.widgets.services_panel import ServicesPanel
from rosight.widgets.tf_panel import TfPanel
from rosight.widgets.topics_panel import TopicsPanel
from rosight.widgets.yaml_form import YamlFormScreen

_DISPLAY = {
    "left_square_bracket": "[",
    "right_square_bracket": "]",
    "slash": "/",
    "escape": "esc",
    "equals_sign": "=",
    "plus": "+",
    "minus": "-",
}


def _keys(cls) -> list[tuple[str, str]]:
    out = []
    for b in cls.BINDINGS:
        key, action = (b.key, b.action) if isinstance(b, Binding) else (b[0], b[1])
        first = key.split(",")[0]
        out.append((_DISPLAY.get(first, first), action))
    return out


@pytest.mark.parametrize(
    "cls",
    [
        RosightApp,
        TopicsPanel,
        MessageTree,
        NodesPanel,
        ServicesPanel,
        ActionsPanel,
        ParamsPanel,
        PlotPanel,
        TfPanel,
        BagsPanel,
        InterfacesPanel,
        ImagePreviewScreen,
        YamlFormScreen,
    ],
)
def test_every_binding_is_documented(cls):
    missing = [
        (key, action)
        for key, action in _keys(cls)
        if f"`{key}`" not in HELP_TEXT and not action.startswith("tab(")
    ]
    assert not missing, f"{cls.__name__} bindings missing from help: {missing}"


def test_every_palette_command_is_documented():
    app = RosightApp()
    for name in app._commands:
        if name in {"q", "exit"}:  # aliases of quit
            continue
        assert f"`{name}" in HELP_TEXT, f":{name} missing from help"


def test_help_has_no_phantom_keys():
    for phantom in ("hz monitor", "bandwidth monitor", "planned", "not yet"):
        assert phantom not in HELP_TEXT
