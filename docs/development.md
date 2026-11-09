# Development

## Local setup

```bash
git clone https://github.com/matthewyjiang/petal.git
cd petal
uv tool install --editable .
```

## Quality gates

Run the same checks used by CI:

```bash
uv run --extra quality ruff check .
uv run --extra quality ruff format --check .
uv run --extra quality basedpyright
uv run --extra test pytest -q
```

To apply Ruff formatting locally:

```bash
uv run --extra quality ruff format .
```

Unit tests use fake subprocess runners and do not require network, real ROS, apt, rosdep, uv, or colcon.

## Real ROS smoke test

A real ROS integration smoke test is available but intentionally excluded from the default test suite. It validates ROS detection, `.petal/venv` creation with `--system-site-packages`, `petal init`, `petal sync`, `petal status`, and `colcon deps`. It also checks current-shell activation, `petal run` (including workspace discovery from subdirectories), and `petal shell` for each installed bash/zsh. The run/shell checks clear inherited ROS paths first so a previously sourced environment cannot mask activation failures. The run/shell probes use the ROS-compatible venv interpreter to create a real `rclpy` node and publish a `std_msgs/String` message; they do not just check imports.

Run it manually in GitHub Actions with the **Real ROS smoke** workflow, or locally from a ROS machine/container that has `rosdep`, `apt-get`, `uv`, and `colcon` installed:

```bash
source /opt/ros/$ROS_DISTRO/setup.bash
uv tool install --editable ".[colcon]"
PETAL_REAL_ROS_SMOKE=1 tests/integration/real_ros_smoke.sh
```

## Docs site

This documentation site is built with VitePress.

Preview locally:

```bash
cd docs
npm install
npm run docs:dev
```

Build locally:

```bash
cd docs
npm install
npm run docs:build
```

The GitHub Pages workflow publishes the site from `main`.
