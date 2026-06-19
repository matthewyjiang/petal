# Philosophy

Petal exists because ROS Python environments are not ordinary Python app environments.

ROS 2 and Ubuntu LTS are intentionally paired: Ubuntu freezes package versions, and ROS builds against them. Packages like `python3-numpy`, `python3-opencv`, and `python3-transforms3d` exist so the ROS stack shares a known, coherent set of versions. Replacing them with pip-installed copies often creates a broken ROS environment, not a better one.

Petal works with this model instead of fighting it.

## The short version

- Prefer apt for anything available as a `python3-*` distro package.
- Use rosdep and ROS/system packages before PyPI.
- Put PyPI-only packages in a workspace-local `.petal/venv`.
- Create that venv with `--system-site-packages` so ROS Python modules remain visible.
- Never pip install into system Python.

The result is a workspace that stays compatible with ROS while still letting you use the PyPI packages your project needs, cleanly and reproducibly.

## Why apt-first?

In many Python projects, the newest PyPI package is the natural default. In ROS, that assumption can be harmful.

ROS packages are compiled, tested, and distributed against the Python packages provided by the target Ubuntu distribution. If a workspace shadows those packages with pip-installed versions, imports may still appear to work while native extensions, ABI expectations, or transitive dependencies no longer match the rest of the ROS install.

Petal treats distro packages as the stable base and PyPI as the extension point.

## Why a shared Python view?

Petal is dependency management, not ROS node isolation. ROS2 expects nodes, tools, and packages to share one coherent Python view. Petal preserves that expectation by using a venv that can see system site packages instead of hiding ROS modules behind a fully isolated virtual environment.

That is why the managed venv is created with `--system-site-packages`.

## Why not just Docker?

Docker is excellent for CI, demos, deployment images, and reproducing a full OS environment.

Petal is for the common case where you are developing directly on a ROS machine and want dependencies to stay aligned with that machine's Ubuntu/ROS install.

Use Docker for OS-level isolation. Use Petal for workspace-level dependency management without pip installs into system Python.
