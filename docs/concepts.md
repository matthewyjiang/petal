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

Keys from `package.xml` are rosdep keys, not PyPI names, so they only resolve through steps 1 and 2. Rosdep rules that map a key to pip still work. Petal never guesses a PyPI package for an unknown key, because a typo or a stale rosdep cache could otherwise install an unrelated project with the same name.

Petal also skips:

- packages that live in the workspace itself, since colcon builds them;
- dependencies whose `condition` attribute is false for ROS 2 and the workspace's distro, for example `condition="$ROS_VERSION == 1"`.

If a key still cannot be resolved, `petal sync` fails and lists it. Run `rosdep update`, or tell Petal what to do with the key:

```toml
[overrides]
some_key = { pip = "some-pypi-name" }
other_key = { apt = "libfoo-dev" }
unneeded_key = { skip = true }
```

## The managed venv

PyPI packages are installed into `.petal/venv`, not into system Python.

The venv is always created with `--system-site-packages` so modules provided by ROS and apt, such as `rclpy`, remain importable at runtime.

### Pip never shadows system packages

ROS packages are built against the Python packages your system provides. A second copy of numpy or PyYAML in `.petal/venv` would take precedence over the system copy and can break them. Petal prevents this:

- A Python requirement the system already satisfies, such as `requests>=2` from a `setup.cfg`, resolves to the system copy and installs nothing.
- Every system distribution is pinned in `.petal/constraints.txt`. PyPI packages are resolved against those pins, and their dependencies are installed with `--no-deps`, minus anything the system provides.
- If a requirement needs a different version than the system has, `petal sync` fails and shows uv's explanation instead of installing a shadowing copy.

To shadow a system package on purpose, declare it explicitly as a pip dependency, for example `petal add --pip numpy ">=2"`. Such packages are left out of the constraints.

`petal sync` warns when `.petal/venv` already contains a copy of a system package, for example one installed by an older petal version. Run `petal clean && petal sync` to remove it.

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
