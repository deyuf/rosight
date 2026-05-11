"""Allow ``python -m rosight`` to launch the TUI."""

from rosight.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
