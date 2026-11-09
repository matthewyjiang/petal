# Getting started

## Requirements

Petal requires:

- Python 3.10+
- ROS2 installed under `/opt/ros/<distro>`
- `rosdep`
- apt tools
- `uv`

## Install

```bash
uv tool install petal-ros
```

To use the `colcon deps` verb, install the colcon extra:

```bash
uv tool install "petal-ros[colcon]"
```

For local development:

```bash
git clone https://github.com/matthewyjiang/petal.git
cd petal
uv tool install --editable .
```

For one-off local runs without installing the `petal` command:

```bash
uv run petal --help
```

## Initialize a workspace

Run from a ROS2 workspace root:

```bash
petal init
```

This creates:

- `petal.toml` for declared workspace dependencies.
- `.petal/venv` for PyPI-managed packages.
- `.petal/activate` for shell activation.

## Add dependencies

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

By default, Petal resolves dependencies apt/ROS-first and only uses PyPI when needed. You can force a source when necessary:

```bash
petal add --apt numpy
petal add --pip some-pypi-only-package
```

## Sync and verify

```bash
petal sync
petal status
```

`petal status` exits with code `2` when the workspace is out of sync.

## Work in the environment

Open an interactive shell with ROS and the workspace venv ready:

```bash
petal shell
# Work as usual, then type exit to return to your previous shell.
```

Petal uses bash or zsh from `$SHELL` (bash when unset). Override with `petal shell --shell bash` or `--shell zsh`. Your normal shell configuration loads before Petal activates the environment; no dotfiles are edited.

For one command, no activation is needed:

```bash
petal run python my_node.py
petal run ros2 launch my_package launch.py
petal run colcon build
```

Both commands work from workspace subdirectories without changing your current directory. They use the existing environment and never install or sync dependencies automatically.

To activate in your **current** shell instead, the existing commands still work:

```bash
source <(petal activate)  # bash/zsh, including from subdirectories
```

Or, from the workspace root (also works in POSIX sh):

```sh
. .petal/activate
```
