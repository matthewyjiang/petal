---
layout: home

hero:
  name: Petal
  text: Workspace-scoped Python dependency manager for ROS2
  tagline: Keep ROS Python environments coherent while using the PyPI packages your workspace needs.
  actions:
    - theme: brand
      text: Get started
      link: /getting-started
    - theme: alt
      text: Philosophy
      link: /philosophy

features:
  - title: ROS-first philosophy
    details: Preserve the Ubuntu/ROS Python base instead of shadowing it with pip-installed packages.
    link: /philosophy
    linkText: Read why
  - title: Workspace-local state
    details: Install PyPI-only packages into .petal/venv, never system Python.
  - title: Reproducible installs
    details: Track requested dependencies in petal.toml and resolved sources in petal.lock.
---

## Quickstart

```bash
uv tool install petal-ros

petal init
petal sync
source <(petal activate)
```

## Examples

```bash
petal add numpy
petal add huggingface
petal add ultralytics ">=8,<9"
petal add cv_bridge
```
