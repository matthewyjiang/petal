# petal

Workspace-scoped Python dependency manager for ROS2.

Petal uses a manifest and lock file to prefer ROS/apt-provided Python packages, then falls back to installing pip packages into a workspace venv. This is dependency management, not node isolation: ROS2 still runs in one shared Python interpreter view.

Any venv created by petal uses `--system-site-packages` and must be activated after ROS:

```bash
source .petal/activate
```
