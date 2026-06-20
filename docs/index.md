---
layout: home

hero:
  name: 🌸 Petal
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
  - icon: 🤖
    title: ROS-first philosophy
    details: Preserve the Ubuntu/ROS Python base instead of shadowing it with pip-installed packages.
    link: /philosophy
    linkText: Read why
  - icon: 🌱
    title: Workspace-local state
    details: Install PyPI-only packages into .petal/venv, never system Python.
  - icon: 🔒
    title: Reproducible installs
    details: Track requested dependencies in petal.toml and resolved sources in petal.lock.
---
