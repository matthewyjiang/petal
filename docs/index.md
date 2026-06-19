---
layout: home

hero:
  name: Petal
  text: Workspace-scoped Python dependency manager for ROS2
  tagline: Resolve apt-first, fall back to PyPI when needed, and keep ROS Python environments coherent.
  actions:
    - theme: brand
      text: Get started
      link: /getting-started
    - theme: alt
      text: Why Petal?
      link: /philosophy

features:
  - title: ROS-aware by default
    details: Prefer ROS, rosdep, and Ubuntu packages before PyPI to avoid shadowing libraries ROS was built against.
  - title: Workspace-local state
    details: Install PyPI-only packages into .petal/venv instead of system Python.
  - title: Reproducible installs
    details: Track requested dependencies in petal.toml and resolved sources in petal.lock.
---

## Why Petal?

ROS Python environments are not ordinary Python app environments. ROS builds against the packages shipped by Ubuntu, and replacing those packages with pip-installed copies can break an otherwise healthy workspace.

Petal's philosophy is simple: keep the ROS/Ubuntu base intact, install PyPI-only packages in workspace-local state, and never pip into system Python.

[Read the philosophy →](/philosophy)

## Quickstart

Install Petal:

```bash
uv tool install petal-ros
```

From a ROS2 workspace root:

```bash
petal init
petal sync
petal status
source <(petal activate)
```

For POSIX shells without process substitution:

```sh
. .petal/activate
```

## Common examples

```bash
petal add numpy
petal add huggingface
petal add ultralytics ">=8,<9"
petal add cv_bridge
```
