"""User configuration loading.

Configuration lives at ``$XDG_CONFIG_HOME/rosight/config.toml`` (falling back
to ``~/.config/rosight/config.toml``). Missing files are not an error — the
defaults are applied automatically.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore[no-redef]


CONFIG_FILENAME = "config.toml"


@dataclass(frozen=True, slots=True)
class PlotConfig:
    window_seconds: float = 30.0
    max_points: int = 5_000
    refresh_hz: float = 15.0
    show_legend: bool = True


@dataclass(frozen=True, slots=True)
class StatsConfig:
    window_seconds: float = 5.0
    max_samples: int = 4096


@dataclass(frozen=True, slots=True)
class UIConfig:
    theme: str = "rosight-dark"
    refresh_hz: float = 10.0
    discovery_period: float = 1.0  # how often to refresh topic/node lists
    vim_keys: bool = True


@dataclass(frozen=True, slots=True)
class RosConfig:
    domain_id: int | None = None  # None -> inherit ROS_DOMAIN_ID
    qos_profile: str = "auto"  # auto | sensor_data | reliable | best_effort
    queue_depth: int = 10


@dataclass(frozen=True, slots=True)
class Config:
    ui: UIConfig = field(default_factory=UIConfig)
    plot: PlotConfig = field(default_factory=PlotConfig)
    stats: StatsConfig = field(default_factory=StatsConfig)
    ros: RosConfig = field(default_factory=RosConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Config:
        """Build a Config from a parsed TOML dict, ignoring unknown keys."""
        return cls(
            ui=_merge(UIConfig(), data.get("ui", {})),
            plot=_merge(PlotConfig(), data.get("plot", {})),
            stats=_merge(StatsConfig(), data.get("stats", {})),
            ros=_merge(RosConfig(), data.get("ros", {})),
        )


def _merge(default: Any, overrides: dict[str, Any]) -> Any:
    """Replace dataclass fields with values from a mapping; ignore unknowns."""
    if not overrides:
        return default
    valid = {f.name for f in default.__dataclass_fields__.values()}  # type: ignore[attr-defined]
    filtered = {k: v for k, v in overrides.items() if k in valid}
    return replace(default, **filtered)


def config_path() -> Path:
    """Return the resolved config file path (does not require it to exist)."""
    base = os.environ.get("ROSIGHT_CONFIG")
    if base:
        return Path(base).expanduser()
    return Path(user_config_dir("rosight")) / CONFIG_FILENAME


def load_config(path: Path | None = None) -> Config:
    """Load configuration from ``path`` (or the default location).

    Returns defaults if the file does not exist. Raises ``ValueError`` only
    if the file exists but is malformed.
    """
    p = path or config_path()
    if not p.exists():
        return Config()
    try:
        with p.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Invalid TOML in {p}: {e}") from e
    return Config.from_dict(data)


# ---------------------------------------------------------------------------
# Runtime user state (theme choice, ...). Kept separate from ``config.toml``
# so the user's hand-written config is never rewritten by the app.
# ---------------------------------------------------------------------------

STATE_FILENAME = "state.toml"


def state_path() -> Path:
    return Path(user_config_dir("rosight")) / STATE_FILENAME


def load_user_state() -> dict[str, Any]:
    """Return the persisted user-state dict (theme, etc.). Empty on miss."""
    p = state_path()
    if not p.exists():
        return {}
    try:
        with p.open("rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def save_user_state(state: dict[str, Any]) -> None:
    """Atomically replace the state file with ``state``.

    Best-effort: failure to write (read-only FS, etc.) is silently swallowed
    so we never crash the app over a cosmetic preference.
    """
    p = state_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for k, v in state.items():
                if isinstance(v, str):
                    escaped = v.replace("\\", "\\\\").replace('"', '\\"')
                    f.write(f'{k} = "{escaped}"\n')
                elif isinstance(v, bool):
                    f.write(f"{k} = {'true' if v else 'false'}\n")
                elif isinstance(v, (int, float)):
                    f.write(f"{k} = {v}\n")
        tmp.replace(p)
    except Exception:
        pass
