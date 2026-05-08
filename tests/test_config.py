from __future__ import annotations

from pathlib import Path

import pytest

from lazyros.config import Config, load_config


def test_defaults():
    c = Config()
    assert c.ui.theme == "lazyros-dark"
    assert c.plot.window_seconds == 30.0
    assert c.ros.queue_depth == 10


def test_load_missing_returns_defaults(tmp_path: Path):
    path = tmp_path / "nope.toml"
    cfg = load_config(path)
    assert cfg == Config()


def test_load_overrides(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
        [ui]
        theme = "light"
        refresh_hz = 30

        [plot]
        window_seconds = 60.0

        [ros]
        domain_id = 5
        """
    )
    cfg = load_config(path)
    assert cfg.ui.theme == "light"
    assert cfg.ui.refresh_hz == 30.0
    assert cfg.plot.window_seconds == 60.0
    assert cfg.ros.domain_id == 5
    # untouched fields keep defaults
    assert cfg.plot.max_points == 5000


def test_load_unknown_keys_ignored(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text(
        """
        [ui]
        nope = 123
        theme = "x"
        """
    )
    cfg = load_config(path)
    assert cfg.ui.theme == "x"


def test_invalid_toml_raises(tmp_path: Path):
    path = tmp_path / "config.toml"
    path.write_text("not = toml = ???")
    with pytest.raises(ValueError):
        load_config(path)
