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

To shadow a system package on purpose, declare it as a pip dependency under `[deps]`, for example with `petal add --pip numpy ">=2"`, which writes `numpy = { pip = ">=2" }`. Such packages are left out of the constraints. `[overrides]` entries do not allow shadowing.

When the system changes so that the lock no longer fits, for example because a dependency locked to the system no longer satisfies its version spec, or because a package locked to PyPI is now provided by the system, the next `petal sync` resolves again. System updates that keep the lock valid, such as a compatible `apt upgrade`, do not touch it.

`petal sync` warns when `.petal/venv` already contains a copy of a system package, for example one installed by an older petal version. Run `petal clean && petal sync` to remove it.

## Manifest and lockfile

Petal records requested dependencies in `petal.toml`:

```toml
[deps]
numpy = ">=1.24"
ultralytics = "*"
```

After resolution and installation, Petal writes `petal.lock` with the resolved source for each dependency. The lock is safe to commit: it records what you declared, which source was chosen, and pinned versions for the whole PyPI closure: your PyPI dependencies and everything they pull in (marked `transitive`). A pulled-in package that the system provides is pinned too: Petal leaves it to the system here, and a machine without it installs the locked version. System packages are recorded without versions, so the lock does not change with whichever machine resolved it.

When Petal resolves again, it keeps locked and installed PyPI versions where they are still compatible. Adding one dependency does not upgrade the others.

`petal sync --frozen` installs exactly what `petal.lock` records and never rewrites it. It resolves nothing: apt gets the locked debs and pip gets the locked pins with `--no-deps`. It fails if the lock is out of date with `petal.toml` or the workspace, or if the lock does not fit this machine's system packages. System packages that come from the lock's own apt entries are checked after apt has installed them.

## Docker and Petal

Docker is useful for CI, demos, deployment images, and reproducing a full OS environment.

Petal is for the common case where you develop directly on a ROS machine and want dependencies to stay aligned with that machine's Ubuntu/ROS install.

Use Docker for OS-level isolation. Use Petal for workspace-level dependency management without pip installs into system Python. For more context, see [Philosophy](/philosophy).
