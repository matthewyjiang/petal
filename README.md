# petal

Workspace-scoped Python dependency manager for ROS2.

Petal discovers Python dependencies in a ROS2 workspace, resolves apt-first, falls back to PyPI when needed, installs into workspace-local state, and writes `petal.lock`.

## Philosophy

ROS 2 and Ubuntu LTS are intentionally paired: Ubuntu freezes package versions, and ROS builds against them. Packages like `python3-numpy`, `python3-opencv`, and `python3-transforms3d` exist so the ROS stack shares a known, coherent set of versions. Replacing them with pip-installed copies often creates a broken ROS environment, not a better one.

Petal works with this model instead of fighting it:

- Prefer apt for anything available as a `python3-*` distro package. Petal records these in `petal.toml` so installs are reproducible, but it does not try to replace what ROS was built against.
- Use an isolated `.petal/venv` for everything else: research packages, custom libraries, and PyPI-only tools. The venv uses `--system-site-packages` so it can see apt-installed ROS Python packages without duplicating them.
- Never pip into system Python. That is what causes dependency conflicts; Petal makes it unnecessary.

The result is a workspace that stays compatible with ROS while still letting you use the PyPI packages your project needs, cleanly and reproducibly.

### Docker

Docker is great for CI, demos, deployment images, and reproducing a full OS environment. Petal is for the common case where you are developing directly on a ROS machine and want dependencies to stay aligned with that machine's Ubuntu/ROS install.

Use Docker for OS-level isolation. Use Petal for workspace-level dependency management without pip installs into system Python.

## Install

```bash
uv tool install petal-ros
```

If you use the colcon verb, install the colcon extra:

```bash
uv tool install "petal-ros[colcon]"
```

Local development with uv, no system `pip` required:

```bash
git clone https://github.com/matthewyjiang/petal.git
cd petal
uv tool install --editable .
```

For one-off local runs without installing the `petal` command:

```bash
uv run petal --help
```

Requires Python 3.10+, ROS2 under `/opt/ros/<distro>`, `rosdep`, apt tools, and `uv`.

## Quickstart

From a ROS2 workspace root:

```bash
petal init
petal sync
petal status
source <(petal activate)
```

## Examples

Apt-resolved package:

```bash
petal add numpy
```

PyPI package:

```bash
petal add huggingface
```

Version spec:

```bash
petal add ultralytics ">=8,<9"
```

Rosdep-resolved ROS package:

```bash
petal add cv_bridge
```

## Commands

| Command | Description |
| --- | --- |
| `petal init` | Create `petal.toml` and `.petal/venv`. |
| `petal add <name> [spec]` | Add a dependency and sync it. Use `--apt` or `--pip` to force a source. |
| `petal remove <name>` | Remove a dependency. |
| `petal sync` | Resolve, install, and write `petal.lock`. |
| `petal status` | Report drift; exits 2 when the workspace is out of sync. |
| `petal activate` | Print the ROS + venv activation snippet. |
| `petal clean` | Remove `.petal/venv`. |

Common sync flags: `--yes`, `--no`, `--dry-run`, `--frozen`.

`petal sync` and `petal add` print the resolved source for each dependency before installing.

## Manifest

Petal records workspace dependencies in `petal.toml`:

```toml
[deps]
numpy = ">=1.24"
ultralytics = "*"
```

Resolution order: ROS/system modules, `rosdep`, apt (`python3-<name>`), then PyPI. Use `petal add --apt` or `petal add --pip` when you need to force a source.

## Colcon Verb

Petal ships a `colcon deps` verb. Install with the colcon extra:

```bash
uv tool install "petal-ros[colcon]"
```

Then from a ROS2 workspace root:

```bash
colcon deps sync              # resolve and install dependencies
colcon deps status            # report drift; exits 2 on drift/missing/change
colcon deps sync --dry-run    # show plan, install nothing
colcon deps sync --frozen     # enforce petal.lock
colcon deps sync --workspace /path/to/ws  # explicit workspace path
```

`colcon deps` is a thin wrapper around `petal sync` / `petal status` and honours the same flags.

## Agent Skill

This repo includes an installable agent skill with Petal CLI usage guidance:

```bash
petal install-agent-skill
```

After installing, coding agents that support `~/.agents/skills` can load the `petal-cli` skill when users ask about Petal.

## Development

```bash
uv run --with pytest pytest -q
```

Unit tests use fake subprocess runners and do not require network, real ROS, apt, rosdep, uv, or colcon.
