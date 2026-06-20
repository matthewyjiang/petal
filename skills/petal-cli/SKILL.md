---
name: petal-cli
description: Use when working with Petal, the workspace-scoped Python dependency manager for ROS2. Covers installing petal-ros, initializing a workspace, adding/removing dependencies, syncing apt/PyPI/rosdep dependencies, checking drift, activation, colcon deps, manifests, lockfiles, and common ROS Python constraints.
---

# Petal CLI

Petal is a workspace-scoped Python dependency manager for ROS2. It discovers Python dependencies in a ROS2 workspace, resolves apt-first, falls back to PyPI when needed, installs pip packages into `.petal/venv`, and writes `petal.lock`.

Use this skill whenever you need to work with Petal or `colcon deps`, including installing, configuring, running, troubleshooting, or automating the CLI.

## Official Docs

For complete and up-to-date documentation, see <https://matthewyjiang.github.io/petal/>.

Use this skill as the fast path for common workflows and operational guidance. Consult the docs when command behavior, flags, install instructions, or troubleshooting details may have changed.

## Key Constraints

- Petal is dependency management, not ROS node isolation. ROS2 uses one shared Python interpreter view.
- Petal venvs must use `--system-site-packages` so ROS Python modules like `rclpy` remain visible.
- Distro/apt packages should win over pip by default to avoid shadowing ROS-linked packages.
- Pip installs target `.petal/venv`; never install into system site-packages.
- Run commands from the ROS2 workspace root unless `--workspace` is supported and provided.

## Install

```bash
uv tool install petal-ros
```

For the colcon verb:

```bash
uv tool install "petal-ros[colcon]"
```

Local development install with uv, no system `pip` required:

```bash
git clone https://github.com/matthewyjiang/petal.git
cd petal
uv tool install --editable .
```

For one-off local runs without installing the `petal` command:

```bash
uv run petal --help
```

Requirements: Python 3.10+, ROS2 under `/opt/ros/<distro>`, `rosdep`, apt tools, and `uv`.

## Quickstart

From a ROS2 workspace root:

```bash
petal init
petal add numpy
petal sync
petal status
source <(petal activate)  # bash/zsh
```

For POSIX shells without process substitution, use the generated workspace script:

```sh
. .petal/activate
```

## Core Commands

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
                         # bash/zsh: source <(petal activate)
                         # POSIX sh: . .petal/activate
petal clean             # remove .petal/venv
```

Notes:

- `petal add` and `petal sync` print the resolved source for each dependency before installing.
- If `petal add` is declined, cancelled, or run with `--dry-run`, `petal.toml` stays unchanged.
- Use `petal sync --dry-run` or `petal sync --no` before changing a workspace if the user only wants a plan.

## Dependency Examples

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

Version spec:

```bash
petal add requests '>=2.31'
```

## Manifest Format

`petal.toml` example:

```toml
[workspace]
ros_distro = "humble"
python_version = "3.10"

[deps]
numpy = ">=1.24"
huggingface = ">=0.0.1"
some-system-lib = { apt = "libfoo-dev" }

[overrides]
ml_collections = { pip = "ml-collections" }
```

Resolution order: ROS/system modules, `rosdep`, apt (`python3-<name>`), then PyPI.

## Colcon Verb

If installed with `petal-ros[colcon]`, use:

```bash
colcon deps sync
colcon deps status
colcon deps sync --dry-run
colcon deps sync --frozen
colcon deps sync --workspace /path/to/ws
```

`colcon deps` is a thin wrapper around `petal sync` / `petal status` and honors the same flags.

## Troubleshooting Patterns

- **`rclpy` or ROS Python imports missing**: ensure `.petal/venv` was created with system site packages, then re-run `petal init` or recreate with `petal clean && petal init`.
- **Unexpected pip shadowing**: prefer apt/rosdep overrides in `petal.toml` when a dependency has ROS-linked native packages.
- **CI wants no mutation**: use `petal status`; treat exit code `2` as dependency drift.
- **Need deterministic install**: commit `petal.toml` and `petal.lock`, then use `petal sync --frozen`.
- **Only want to preview**: use `petal sync --dry-run` or `petal sync --no`.

## Suggested Agent Behavior

When helping with Petal:

1. Ask for the ROS distro, workspace root, and dependency name/spec if missing.
2. Prefer commands that do not mutate state first (`status`, `sync --dry-run`) unless the user explicitly asks to install.
3. Explain whether a dependency should resolve through ROS/system, rosdep, apt, or PyPI.
4. Remind users to activate before running ROS Python code that needs Petal-managed packages. Prefer `source <(petal activate)` for bash/zsh and `. .petal/activate` for POSIX shells without process substitution.
