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

Local development:

```bash
git clone https://github.com/matthewyjiang/petal.git
cd petal
python3 -m pip install -e .
```

Requires Python 3.10+, ROS2 under `/opt/ros/<distro>`, `rosdep`, apt tools, and preferably `uv`.

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

Rosdep-resolved ROS package:

```bash
petal add cv_bridge
```

## Commands

```bash
petal init              # create petal.toml and .petal/venv
petal add <name> [spec] # add dependency and sync it
petal remove <name>     # remove dependency from manifest and venv
petal sync              # resolve, install, write petal.lock
petal sync --yes        # skip install prompt
petal sync --no         # show plan, install nothing
petal sync --dry-run    # show commands, install nothing
petal sync --frozen     # enforce petal.lock
petal status            # report drift; exits 2 on drift/missing/change
petal activate          # print shell snippet for ROS + venv activation
petal clean             # remove .petal/venv
```

`petal sync` and `petal add` print the resolved source for each dependency before installing. If `petal add` is declined, cancelled, or run with `--dry-run`, `petal.toml` stays unchanged.

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
