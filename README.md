# petal

Workspace-scoped Python dependency manager for ROS2.

Petal discovers Python dependencies in a ROS2 workspace, resolves apt-first, falls back to PyPI when needed, installs pip packages into `.petal/venv`, and writes `petal.lock`.

Petal is dependency management, not node isolation. ROS2 still runs in one shared Python interpreter view, so petal venvs are created with `--system-site-packages`.

## Install

```bash
python3 -m pip install git+https://github.com/matthewyjiang/petal.git
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
petal add numpy
petal sync
petal status
source .petal/activate
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

## Development

```bash
uv run --with pytest pytest -q
```

Unit tests use fake subprocess runners and do not require network, real ROS, apt, rosdep, uv, or colcon.
