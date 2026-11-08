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
| `--frozen` | Require the existing lockfile to match. |

## `petal status`

Report dependency drift, missing packages, or manifest hash changes.

```bash
petal status
```

Returns exit code `2` when the workspace is out of sync.

## `petal activate`

Print the ROS + venv activation snippet.

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
