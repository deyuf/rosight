from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from lazyrosplus.config import (
    Config,
    load_config,
    load_user_state,
    save_user_state,
    state_path,
)


def test_defaults():
    c = Config()
    assert c.ui.theme == "lazyrosplus-dark"
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


def test_user_state_roundtrip(tmp_path: Path):
    """Persisting + reloading user state should round-trip simple values."""
    state_file = tmp_path / "state.toml"
    with patch("lazyrosplus.config.state_path", return_value=state_file):
        assert load_user_state() == {}  # missing file is fine
        save_user_state({"theme": "textual-light", "vim_keys": True, "count": 7})
        assert state_file.exists()
        loaded = load_user_state()
        assert loaded["theme"] == "textual-light"
        assert loaded["vim_keys"] is True
        assert loaded["count"] == 7


def test_user_state_handles_unwritable_dir(tmp_path: Path):
    """save_user_state must never raise — it's best-effort."""
    bad_path = tmp_path / "nonexistent" / "ro" / "state.toml"
    with patch("lazyrosplus.config.state_path", return_value=bad_path):
        # Make the parent unwritable to simulate failure.
        bad_path.parent.parent.mkdir(parents=True)
        bad_path.parent.parent.chmod(0o500)
        try:
            save_user_state({"theme": "x"})  # must not raise
        finally:
            bad_path.parent.parent.chmod(0o700)


def test_state_path_default():
    p = state_path()
    assert p.name == "state.toml"
