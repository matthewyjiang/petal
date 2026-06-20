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

A real ROS integration smoke test is available but intentionally excluded from the default test suite. It validates that Petal can detect ROS, create a `.petal/venv` with `--system-site-packages`, run `petal init`, `petal sync`, `petal status`, exercise `colcon deps`, and emit an activation snippet that exposes ROS Python modules.

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
