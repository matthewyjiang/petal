# Philosophy

ROS Python environments are not ordinary Python app environments. ROS 2 and Ubuntu LTS are intentionally paired: Ubuntu freezes package versions, and ROS builds against them. Packages like `python3-numpy`, `python3-opencv`, and `python3-transforms3d` exist so the ROS stack shares a known, coherent set of versions. Replacing them with pip-installed versions often creates a broken ROS environment.

## Core Tenets

- Prefer apt for anything available as a `python3-*` distro package.
- Use rosdep and ROS/system packages before PyPI.
- Put PyPI-only packages in a workspace-local `.petal/venv`.
- Create that venv with `--system-site-packages` so ROS Python modules remain visible.
- Never pip install into system Python.

Thus Petal allows you to to keep your project compatible with ROS while also managing your needed PyPI packages, and helps you keep your dependencies clean and reproducible.

## Why apt-first?

In order to maintain long term support, ROS packages are compiled, tested, and distributed against the Python packages provided by the target Ubuntu LTS distribution. If a workspace shadows those packages with pip-installed versions, imports may still appear to work while native extensions, ABI expectations, or transitive dependencies no longer match the rest of the ROS install.

Petal treats distro packages as the stable base and PyPI as the extension point.

## Why expose system site packages?

ROS prefers Python packages installed through apt into the system Python environment. That includes both ROS modules, such as rclpy, and many Python dependencies that ROS packages commonly rely on, such as numpy, opencv, and transforms3d.

A fully isolated virtual environment would hide those apt-installed packages. That means your workspace might no longer be able to import ROS Python modules or the distro-provided Python packages that the ROS stack was built and tested against.

Petal avoids that problem by creating the managed venv with --system-site-packages. This gives the workspace access to system Python packages, while still allowing PyPI-only dependencies to be installed locally inside .petal/venv.

## Why not just Docker?

Docker is excellent for CI, demos, deployment images, and production-like reproducibility. It is the right tool when you need to capture the entire operating system, ROS distribution, system packages, and runtime environment in one portable image.

Petal is great in smaller-scale, non-production ROS development environments, especially research work, small projects, lab machines, and quick iteration on physical robots. In these settings, developers are often working directly on an Ubuntu/ROS machine that already has the correct system packages installed through apt.

Using Docker for every dependency change can add unnecessary overhead when the real goal is simply to add a few PyPI-only Python packages without breaking the ROS environment.

Use Docker when you need full OS-level isolation and deployment reproducibility, and Petal when you want clean, local dependency management for an existing ROS workspace.
