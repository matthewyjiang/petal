# petal

Workspace-scoped Python dependency manager for ROS2.

Petal fills the gap between hand-managed `requirements.txt` files and full containerization. It discovers Python dependencies from a ROS2 workspace, resolves them apt-first, falls back to pip when needed, installs pip packages into a workspace venv, and records the result in `petal.lock`.

Petal is dependency management, not node isolation. ROS2 still runs in one shared Python interpreter view.

## Why

- Prefer ROS/apt packages when available, avoiding accidental pip shadowing of ROS-linked packages.
- Keep pip fallback packages scoped to the workspace under `.petal/venv`.
- Generate a lock file so CI and teammates can detect drift.
- Integrate with colcon via `colcon deps`.

## ROS Runtime Contract

ROS Python packages such as `rclpy`, `launch`, and `tf2_ros` are provided by `/opt/ros/<distro>` and the system Python path. A normal venv hides those packages, so petal always creates its managed venv with `--system-site-packages` and with the exact Python minor version used by the ROS distro.

Activation order matters. Source ROS first, then the petal venv:

```bash
source .petal/activate
```

The generated helper does both steps:

```bash
source /opt/ros/<distro>/setup.bash
source .petal/venv/bin/activate
```

## Quickstart

From a ROS2 workspace root:

```bash
petal init
petal add numpy
petal sync --dry-run
petal sync
petal status
```

`petal init` writes `petal.toml`, creates `.petal/venv`, and writes `.petal/activate`.

## Install

Prerequisites:

- Python 3.10+
- ROS2 installed under `/opt/ros/<distro>`
- `rosdep`, `apt-cache`, and `dpkg-query` available for full resolution
- `uv` recommended; petal falls back to pip for installs when needed

Install from GitHub:

```bash
python3 -m pip install git+https://github.com/matthewyjiang/petal.git
```

Install for local development:

```bash
git clone https://github.com/matthewyjiang/petal.git
cd petal
python3 -m pip install -e .
```

If your system Python does not have pip installed, use `uv`:

```bash
uv tool install git+https://github.com/matthewyjiang/petal.git
```

Verify the CLI is available:

```bash
petal --help
```

## Manifest

`petal.toml` is the human-edited source of truth:

```toml
[workspace]
ros_distro = "humble"
python_version = "3.10"

[deps]
numpy = ">=1.24"
torch = { pip = ">=2.1" }
some-system-lib = { apt = "libfoo-dev" }

[overrides]
ml_collections = { pip = "ml-collections" }
```

## Commands

```bash
petal init              # detect ROS distro/Python, create manifest and venv
petal add <name> [spec] # add a dependency to petal.toml and sync it
petal remove <name>     # remove a dependency from petal.toml and venv
petal sync              # discover, resolve, install, write petal.lock
petal sync --dry-run    # print apt/pip commands without installing
petal sync --frozen     # enforce petal.lock
petal status            # report drift; exits 2 when drift/missing/changed
petal activate          # print shell snippet to source ROS and venv
petal clean             # remove .petal/venv
```

Examples:

```bash
petal add numpy
petal add rich
petal add scipy
petal add numpy ">=1.24"
petal add rich ">=13" --pip
petal add opencv python3-opencv --apt
petal remove rich
```

`petal add` preserves other manifest sections such as `[overrides]`. `petal remove` drops the manifest entry and uninstalls pip packages from `.petal/venv`; it does not run `apt remove` for system packages.

Colcon wrapper:

```bash
colcon deps sync
colcon deps status
```

## Resolution Order

For each dependency, petal resolves in this order unless the manifest forces a source:

1. ROS/system distro-provided Python modules, such as `rclpy`.
2. `rosdep resolve` mappings.
3. Apt package probe, usually `python3-<name>`.
4. Pip/uv fallback into `.petal/venv`.

Planner conflict checks run before any apt or pip mutation.

## Development

Run tests with `uv` because system Python may not have `pytest`:

```bash
uv run --with pytest pytest -q
```

Focused test example:

```bash
uv run --with pytest pytest -q tests/test_resolve.py
```

Unit tests use fake subprocess runners and fixtures; they do not require network, real ROS, apt, rosdep, uv, or colcon.
