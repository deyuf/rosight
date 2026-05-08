"""Command-line entry point for ``lazyros``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from lazyros.config import Config, config_path, load_config
from lazyros.version import __version__


def _setup_logging(level: str, log_file: Path | None) -> None:
    handlers: list[logging.Handler] = []
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers or [logging.NullHandler()],
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="lazyros",
        description="lazygit-style terminal UI for ROS 2",
    )
    p.add_argument(
        "-c",
        "--config",
        type=Path,
        help=f"path to config TOML (default: {config_path()})",
    )
    p.add_argument("--domain-id", type=int, help="override ROS_DOMAIN_ID")
    p.add_argument("--node-name", default="lazyros", help="rclpy node name")
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
    )
    p.add_argument(
        "--log-file",
        type=Path,
        help="path to a log file (default: stderr suppressed)",
    )
    p.add_argument(
        "--no-ros",
        action="store_true",
        help="skip ROS 2 initialisation (useful for UI-only debugging)",
    )
    p.add_argument("-V", "--version", action="version", version=f"lazyros {__version__}")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    _setup_logging(args.log_level, args.log_file)

    try:
        cfg: Config = load_config(args.config)
    except ValueError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    if args.domain_id is not None:
        from dataclasses import replace

        cfg = replace(cfg, ros=replace(cfg.ros, domain_id=args.domain_id))

    # Defer Textual import to keep --version fast.
    from lazyros.app import LazyrosApp
    from lazyros.ros.backend import RosBackend

    ros = None
    if args.no_ros:
        ros = RosBackend(node_name=args.node_name, domain_id=cfg.ros.domain_id)
        # leave it un-started; the app will downgrade gracefully.

    app = LazyrosApp(config=cfg, ros=ros)
    return app.run() or 0


if __name__ == "__main__":
    raise SystemExit(main())
