# petal

**[Read the documentation](https://matthewyjiang.github.io/petal/)**

Workspace-scoped Python dependency manager for ROS2.

Petal keeps ROS Python environments coherent: it resolves Ubuntu/ROS packages first, falls back to PyPI only when needed, installs PyPI packages into workspace-local state, and writes `petal.lock` for reproducibility.

```bash
uv tool install petal-ros

petal init
petal sync
source <(petal activate)
```
