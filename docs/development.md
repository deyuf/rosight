# Development guide

## Bootstrap

```bash
git clone https://github.com/deyuf/lazyrosplus
cd lazyrosplus
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,docs]"
```

For ROS-aware development:

```bash
source /opt/ros/<distro>/setup.bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e ".[dev,docs]"
```

## Daily loop

```bash
ruff check src tests              # lint
ruff format src tests             # format
mypy src/lazyrosplus                  # types (advisory)
pytest                            # unit + smoke
pytest --cov=lazyrosplus              # with coverage
mkdocs serve                      # docs preview
```

## Layout reminders

- `src/lazyrosplus/ros/` — anything ROS-aware. `backend.py` is the ONLY module
  that imports `rclpy`; everything else stays import-free of ROS.
- `src/lazyrosplus/widgets/` — one panel per file. Cross-panel calls go via
  `LazyrosPlusApp` rather than direct widget references.
- `src/lazyrosplus/utils/` — pure-Python helpers. Test these first when
  refactoring.
- `tests/` — pure-python tests must run without rclpy. The
  `tiny_message` fixture in `conftest.py` provides a duck-typed ROS
  message for introspection tests.

## Adding a new panel

1. Create `src/lazyrosplus/widgets/foo_panel.py`:
   ```python
   from textual.containers import Vertical
   from textual.binding import Binding
   from textual.widgets import Static

   class FooPanel(Vertical):
       BINDINGS = [Binding("x", "do_something", "X")]
       def compose(self):
           yield Static("hello")
       def action_do_something(self): ...
   ```
2. Register it in `app.py`:
   ```python
   from lazyrosplus.widgets.foo_panel import FooPanel
   ...
   with TabbedContent(initial="topics", id="main-tabs"):
       ...
       with TabPane("Foo", id="foo"):
           yield FooPanel()
   ```
3. Add a number-key binding in `LazyrosPlusApp.BINDINGS`.

## Adding a backend method

Prefer extending `RosBackend` over importing rclpy in widgets. Keep the
new method:

- thread-safe (use `self._lock` for shared state)
- defensive (catch broad exceptions and log them)
- testable (mockable via `_node = MagicMock()`)

## Releasing

1. Bump `__version__` in `src/lazyrosplus/version.py`.
2. Update `CHANGELOG.md`.
3. Tag `vX.Y.Z` and push tags. The `release.yml` workflow builds, attaches
   artifacts to a GitHub release, and publishes to PyPI via trusted
   publishing.

## Style

- ruff handles formatting and import ordering.
- Comments only when they explain *why*. The codebase doesn't document
  obvious mechanics.
- Public APIs get a one-line docstring. Internal helpers usually don't.

## CI

Three workflows:

| File | Trigger | Job |
|------|---------|-----|
| `ci.yml` | push / PR | lint, tests on 3.10–3.12, build, ROS integration on Humble + Jazzy |
| `release.yml` | tag `v*.*.*` | build, GitHub release, PyPI publish |
| `docs.yml` | push to main on docs/ | mkdocs build + deploy to Pages |
