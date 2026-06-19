# Concepts

Petal's design follows from its [ROS-first philosophy](/philosophy): keep the Ubuntu/ROS Python environment coherent, then add workspace-local PyPI packages only where needed.

## Workspace-scoped dependency management

Petal manages dependencies at the ROS2 workspace level. It is not a ROS node isolation tool: ROS2 uses one shared Python interpreter view, and Petal preserves that expectation.

## Resolution order

Petal resolves dependencies in this order:

1. ROS/system modules already available in the ROS Python environment.
2. `rosdep` keys.
3. Ubuntu apt packages, usually `python3-<name>`.
4. PyPI packages installed into `.petal/venv`.

Apt and distro packages win by default to avoid shadowing packages that ROS was built against.

## The managed venv

PyPI packages are installed into `.petal/venv`, not into system Python.

The venv is always created with `--system-site-packages` so modules provided by ROS and apt, such as `rclpy`, remain importable at runtime.

## Manifest and lockfile

Petal records requested dependencies in `petal.toml`:

```toml
[deps]
numpy = ">=1.24"
ultralytics = "*"
```

After resolution and installation, Petal writes `petal.lock` with the resolved source for each dependency. Use `petal sync --frozen` to enforce the existing lockfile.

## Docker and Petal

Docker is useful for CI, demos, deployment images, and reproducing a full OS environment.

Petal is for the common case where you develop directly on a ROS machine and want dependencies to stay aligned with that machine's Ubuntu/ROS install.

Use Docker for OS-level isolation. Use Petal for workspace-level dependency management without pip installs into system Python. For more context, see [Philosophy](/philosophy).
