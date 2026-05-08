"""Allow ``python -m lazyrosplus`` to launch the TUI."""

from lazyrosplus.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
