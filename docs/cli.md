# CLI reference

## `petal init`

Create `petal.toml` and `.petal/venv` for the current workspace.

```bash
petal init
```

## `petal add <name> [spec]`

Add a dependency to `petal.toml` and sync the workspace. Petal resolves the whole workspace, including the new dependency, before it installs anything. If resolution fails or you decline the install, `petal.toml` is left unchanged.

```bash
petal add numpy
petal add ultralytics ">=8,<9"
```

Use `--apt` or `--pip` to force a source:

```bash
petal add --apt numpy
petal add --pip huggingface
```

`--pip` also lets a package shadow a copy the ROS/system Python already provides. Without it, petal uses the system copy. See [Pip never shadows system packages](/concepts#pip-never-shadows-system-packages).

## `petal remove <name>`

Remove a dependency from the manifest.

```bash
petal remove numpy
```

## `petal sync`

Resolve dependencies, install missing packages, and write `petal.lock`.

```bash
petal sync
```

`petal sync` and `petal add` print the resolved source for each dependency before installing.

Common flags:

| Flag | Description |
| --- | --- |
| `--yes` | Accept install prompts. |
| `--no` | Decline install prompts. |
| `--dry-run` | Show the plan without installing. |
| `--frozen` | Install exactly what `petal.lock` records, without resolving anything; fail if the lock is out of date or does not fit this system. Never rewrites the lock. |

## `petal status`

Report dependency drift, missing packages, or manifest hash changes.

```bash
petal status
```

Returns exit code `2` when the workspace is out of sync.

## `petal run <command> [args...]`

Run a command with ROS and the workspace venv loaded, without activating your current shell. Requires bash for the environment bootstrap; the command itself can be any executable.

```bash
petal run python my_node.py
petal run ros2 launch my_package launch.py
petal run colcon build
petal run --workspace /path/to/ws python my_node.py
```

Petal options go before the command. Everything after the executable is passed unchanged to it, including flags such as `--workspace`. An optional `--` separates Petal options from the command.

The command inherits terminal input/output and retains its exit status and signal behavior. Shell expressions require an explicit shell:

```bash
petal run bash -c 'python first.py && python second.py'
```

## `petal shell`

Open an interactive, non-login bash or zsh session with ROS and the workspace venv loaded **after** your normal shell configuration. Type `exit` to return to the parent shell with its environment unchanged.

```bash
petal shell
petal shell --shell zsh
petal shell --workspace /path/to/ws --shell /bin/bash
```

Defaults to `$SHELL`, or `/bin/bash` when unset. Other interactive shells are not supported; select bash or zsh explicitly. Petal uses temporary startup files, honors zsh's `ZDOTDIR` and `.zshenv`, and never edits your dotfiles. Zsh startup files must remain enabled (`setopt RCS`).

Both `run` and `shell` find the workspace from the current directory or its parents and do not change directories themselves. They require an existing workspace environment and never sync or install dependencies automatically.

## `petal activate`

For advanced use when you want to modify your current shell instead of starting a child session.

Print a line that sources `.petal/activate`, which sets up ROS and the petal venv. Both forms below do the same thing. Neither changes your current directory. Use `--shell bash|zsh|sh` to pick which ROS setup script is sourced when auto-detection guesses wrong.

```bash
source <(petal activate)
```

For POSIX shells:

```sh
. .petal/activate
```

## `petal clean`

Remove `.petal/venv`.

```bash
petal clean
```

Run `petal sync` again to recreate workspace-local state.
