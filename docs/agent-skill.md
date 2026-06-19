# Agent skill

Petal includes an installable agent skill with concise CLI usage guidance for coding agents.

## Install

```bash
petal install-agent-skill
```

After installing, agents that support `~/.agents/skills` can load the `petal-cli` skill when users ask about Petal.

## What it covers

The skill captures project-specific guidance for:

- Installing `petal-ros`.
- Initializing a ROS2 workspace.
- Adding, removing, syncing, and checking dependencies.
- Activating `.petal/venv` correctly.
- Understanding Petal's apt-first resolver behavior.
- Avoiding system Python pip installs.
- Using the `colcon deps` verb.

The skill is meant as a convenience for agent-assisted development. It does not change Petal's runtime behavior.
