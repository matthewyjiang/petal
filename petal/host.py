"""Petal's boundary to the machine: the only place commands touch the host.

The CLI performs every side effect (subprocesses, venv creation, ROS detection,
system inspection) through a `Host`, so tests can run the real resolver,
planner and installer against a scripted fake machine.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from petal import env, preflight, session
from petal.resolve.base import (
    Runner,
    StreamRunner,
    default_runner,
    default_stream_runner,
)
from petal.system import SystemPython, inspect_system_python


@dataclass(frozen=True)
class Host:
    # Captured commands: rosdep, apt-cache, dpkg-query, uv pip compile/list.
    runner: Runner = default_runner
    # Commands that change the machine and show progress: apt-get/uv install.
    install_runner: StreamRunner = default_stream_runner
    check_tools: Callable[[], preflight.PreflightReport] = preflight.check
    detect_ros_distro: Callable[[], str] = env.detect_ros_distro
    # Creates or validates the workspace venv; returns its path.
    ensure_venv: Callable[[Path, str], Path] = env.ensure_venv
    inspect_system: Callable[[str], SystemPython] = inspect_system_python
    # Foreground sessions: inherit terminal I/O and never mutate the parent env.
    run_command: Callable[[Path, list[str]], int] = session.run_command
    open_shell: Callable[[Path, str | None], int] = session.open_shell
