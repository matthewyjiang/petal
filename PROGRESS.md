# petal Progress

## Current State

- M1 complete.
- M2 complete.
- M3 complete.
- M4 complete.
- M5 complete.
- M6 complete.
- M7 complete.
- Package scaffold exists.
- `petal init`, `petal activate`, and `petal clean` exist.
- Env detection and venv creation tests pass.
- Workspace dependency discovery tests pass.
- Resolver and distro guard tests pass.
- Planner conflict detection tests pass.
- Installer dry-run, lock writer, and `sync --dry-run` orchestration tests pass.
- Status/drift and frozen lock enforcement tests pass.
- Colcon verb wrapper tests pass.
- `petal add` and `petal remove` tests pass.

## Verification

- Last passing command: `uv run --with pytest pytest -q`
- Result: `64 passed`

## Milestone Tracker

| Milestone | Status | Notes |
| --- | --- | --- |
| M1: env detection | Done | Detect distro, detect ROS Python, create system-site venv, write activate helper, init manifest. |
| M2: discovery | Done | Added `package.xml`, `setup.cfg`, static `setup.py`, `pyproject.toml`, workspace aggregation, overrides, fixture workspaces. |
| M3: resolution + distro guard | Done | Added resolver protocol, distro guard, rosdep parser, apt probe, pip/uv parser, resolution manager, command-output fixtures. |
| M4: planner conflict detection | Done | Added source partitioning, version-spec conflict checks, origin diagnostics, apt/distro-vs-pip shadow warnings. |
| M5: installer + lock | Done | Added installer, dry-run command output, apt installed check, uv/pip install fallback, lock writer, `petal sync --dry-run`. |
| M6: status/drift + frozen | Done | Added lock loader, status report, apt/pip/distro checks, manifest hash drift, exit code 2, frozen lock enforcement. |
| M7: colcon verb | Done | Added `colcon deps` verb wrapper for `sync` and `status`, with entry point and tests. |
| H1: add/remove commands | Done | Added manifest-preserving `petal add` / `petal remove`, pip uninstall fallback, and tests. |

## Implemented Files

- `pyproject.toml`
- `README.md`
- `petal/__init__.py`
- `petal/cli.py`
- `petal/config.py`
- `petal/env.py`
- `petal/models.py`
- `petal/discover/__init__.py`
- `petal/discover/package_xml.py`
- `petal/discover/setup_cfg.py`
- `petal/discover/pyproject.py`
- `petal/discover/workspace.py`
- `petal/resolve/__init__.py`
- `petal/resolve/base.py`
- `petal/resolve/distro.py`
- `petal/resolve/rosdep.py`
- `petal/resolve/apt.py`
- `petal/resolve/pip.py`
- `petal/resolve/manager.py`
- `petal/planner.py`
- `petal/installer.py`
- `petal/status.py`
- `petal/colcon_ext/__init__.py`
- `petal/colcon_ext/verb.py`
- `tests/test_config.py`
- `tests/test_cli.py`
- `tests/test_discovery.py`
- `tests/test_env.py`
- `tests/test_resolve.py`
- `tests/test_planner.py`
- `tests/test_installer.py`
- `tests/test_status.py`
- `tests/test_colcon_verb.py`
- `tests/fixtures/cmd_output/`
- `tests/fixtures/ws_discovery/`
- `tests/fixtures/ws_setup_py/`

## Next Step

Next hardening work:

- improve lock format with hashes for uv output
- add integration test in ROS Docker image
- improve resolver version pinning for apt/rosdep
