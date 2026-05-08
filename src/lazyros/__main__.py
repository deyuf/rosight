"""Allow ``python -m lazyros`` to launch the TUI."""

from lazyros.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
