# Colcon integration

Petal ships a `colcon deps` verb that wraps `petal sync` and `petal status`.

## Install

```bash
uv tool install "petal-ros[colcon]"
```

## Usage

Run from a ROS2 workspace root:

```bash
colcon deps sync
colcon deps status
colcon deps sync --dry-run
colcon deps sync --frozen
```

Use an explicit workspace path when needed:

```bash
colcon deps sync --workspace /path/to/ws
```

## Behavior

`colcon deps` honors the same sync and status behavior as the main Petal CLI:

- `sync` resolves and installs dependencies.
- `status` reports drift and exits with code `2` when the workspace is out of sync.
- `--dry-run` shows the planned install without mutating state.
- `--frozen` enforces `petal.lock`.
