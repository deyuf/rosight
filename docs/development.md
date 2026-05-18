# Development guide

## Bootstrap

```bash
git clone https://github.com/deyuf/rosight
cd rosight
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
mypy src/rosight                  # types (advisory)
pytest                            # unit + smoke
pytest --cov=rosight              # with coverage
mkdocs serve                      # docs preview
```

## Layout reminders

- `src/rosight/ros/` — anything ROS-aware. `backend.py` is the ONLY module
  that imports `rclpy`; everything else stays import-free of ROS.
- `src/rosight/widgets/` — one panel per file. Cross-panel calls go via
  `RosightApp` rather than direct widget references.
- `src/rosight/utils/` — pure-Python helpers. Test these first when
  refactoring.
- `tests/` — pure-python tests must run without rclpy. The
  `tiny_message` fixture in `conftest.py` provides a duck-typed ROS
  message for introspection tests.

## Adding a new panel

1. Create `src/rosight/widgets/foo_panel.py`:
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
   from rosight.widgets.foo_panel import FooPanel
   ...
   with TabbedContent(initial="topics", id="main-tabs"):
       ...
       with TabPane("Foo", id="foo"):
           yield FooPanel()
   ```
3. Add a number-key binding in `RosightApp.BINDINGS`.

## Adding a backend method

Prefer extending `RosBackend` over importing rclpy in widgets. Keep the
new method:

- thread-safe (use `self._lock` for shared state)
- defensive (catch broad exceptions and log them)
- testable (mockable via `_node = MagicMock()`)

## Releasing

Releases are **automatic**. Every push to `main` that passes CI is fed to
`python-semantic-release`, which looks at the conventional commits since
the last tag and decides what to do.

| Commit type | Effect |
|-------------|--------|
| `feat: …` | minor bump (`0.1.x` → `0.2.0`) |
| `fix: …` / `perf: …` | patch bump (`0.1.1` → `0.1.2`) |
| `<anything>!: …` or body contains `BREAKING CHANGE:` | major bump |
| `docs: …` / `ci: …` / `chore: …` / `style: …` / `test: …` / `refactor: …` / `build: …` | no release |

When there's at least one bumping commit since the last tag, the
`publish` job in `ci.yml`:

1. updates `src/rosight/version.py` and `CHANGELOG.md`,
2. commits the bump as `chore(release): X.Y.Z [skip ci]` (the
   `[skip ci]` keyword prevents a self-trigger loop),
3. pushes a `vX.Y.Z` tag,
4. creates a GitHub Release with auto-generated notes,
5. uploads the built sdist + wheel to PyPI via Trusted Publishing
   (configured once on PyPI; see `release.yml` for the legacy
   tag-triggered path).

Pure-docs / pure-CI / pure-chore pushes produce no release — the job
just logs `no version-bumping commits since last tag` and exits.

**Conventional-commit etiquette:**

```text
feat(plot): add 1D-array snapshot plotting
fix(image-preview): stop shadowing Widget._render
docs(plotting): explain colormap fallback
ci(release): wire python-semantic-release
chore(deps): bump textual to 8.3
```

If you need to ship something manually (hotfix while CI is down, etc.),
the legacy path still works: `release.yml` triggers on `v*.*.*` tag
push and `workflow_dispatch`. The auto-pipeline's tag pushes don't
re-fire it (GitHub doesn't re-trigger workflows from
`GITHUB_TOKEN`-pushed refs).

## Style

- ruff handles formatting and import ordering.
- Comments only when they explain *why*. The codebase doesn't document
  obvious mechanics.
- Public APIs get a one-line docstring. Internal helpers usually don't.

## CI

Three workflows:

| File | Trigger | Job |
|------|---------|-----|
| `ci.yml` | push / PR | lint, tests on 3.10–3.12, build, ROS integration on Humble + Jazzy, `publish` job on main pushes |
| `release.yml` | tag `v*.*.*`, `workflow_dispatch` | legacy / manual emergency release path |
| `docs.yml` | push to main on docs/ | mkdocs build + deploy to Pages |
