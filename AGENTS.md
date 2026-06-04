# AGENTS.md

## Verify

- Full test suite: `uv run --with pytest pytest -q`.
- Focused test: `uv run --with pytest pytest -q tests/test_resolve.py` or `uv run --with pytest pytest -q tests/test_resolve.py::test_name`.
- System `python` may not have `pytest`; use the `uv run --with pytest ...` form above.
- `uv run` creates `.venv`, `.pytest_cache`, and sometimes `uv.lock` in this repo; do not commit those unless intentionally changing project workflow.

## Architecture

- CLI entry point is `petal.cli:main`; colcon verb entry point is `petal.colcon_ext.verb:DepsVerb`.
- Core flow for `petal sync`: `discover_workspace` -> `ResolutionManager` -> `build_plan` -> `installer.execute`.
- Data contracts live in `petal/models.py`; keep resolver/planner/installer code using `Dep`, `ResolvedDep`, and `Source` instead of ad hoc dicts.
- `SPEC.md` is the build spec; `PROGRESS.md` tracks completed milestones and next hardening items.

## ROS/Python Constraints

- Petal is dependency management, not ROS node isolation: ROS2 uses one shared Python interpreter view.
- Any managed venv must be created with `--system-site-packages`; otherwise `rclpy` and ROS Python modules break at runtime.
- Detect ROS Python from `/opt/ros/<distro>/lib/python3.*` and use matching `/usr/bin/pythonX.Y`; never assume current interpreter version.
- Apt/distro packages win over pip by default to avoid shadowing ROS-linked packages.
- Pip installs must target `.petal/venv` via explicit interpreter; never install into system site-packages.

## Tests And Fixtures

- Unit tests must not require network, real ROS, apt, rosdep, uv, or colcon; inject fake subprocess runners and use fixtures under `tests/fixtures/`.
- Captured command outputs belong under `tests/fixtures/cmd_output/`.
- Fixture ROS workspaces live under `tests/fixtures/ws_*`; discovery tests depend on `COLCON_IGNORE` skip behavior.
- Optional real ROS integration tests should be opt-in only, not part of default `pytest`.

## Implementation Gotchas

- Do not execute `setup.py`; `petal.discover.setup_cfg.parse_setup_py` only statically parses literal `install_requires`.
- `Source.ROSDEP` deps from `package.xml` still need distro guard first so `rclpy` resolves to `DISTRO` no-op.
- Planner conflict checks must happen before installer mutates apt or pip state.
- `petal status` returns exit code `2` for drift/missing/manifest hash changes; tests assert this.

## Release

Publishing runs from GitHub Actions when a `v*` tag is pushed. PyPI should be configured for trusted publishing with project `petal-ros`, owner `matthewyjiang`, repository `petal`, workflow `publish.yml`, and environment `pypi`.
