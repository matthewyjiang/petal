from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from packaging.utils import canonicalize_name

from petal.models import Dep, ResolvedDep


class Resolver(Protocol):
    def can_resolve(self, dep: Dep) -> bool: ...

    def resolve(self, dep: Dep) -> ResolvedDep | None: ...


class Runner(Protocol):
    def __call__(self, cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]: ...


def default_runner(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **kwargs,
        )
    except FileNotFoundError:
        # Return a failed result so callers handle it the same as a non-zero exit.
        return subprocess.CompletedProcess(
            cmd, returncode=127, stdout="", stderr=f"{cmd[0]}: command not found"
        )


def canonical(name: str) -> str:
    return canonicalize_name(name.replace("_", "-"))


def python_apt_name(name: str) -> str:
    value = canonical(name)
    if value.startswith("python3-"):
        return value
    return f"python3-{value}"


def dep_requirement(dep: Dep) -> str:
    return f"{dep.name}{dep.version_spec}" if dep.version_spec else dep.name


def venv_python(venv: Path) -> Path:
    return venv / "bin" / "python"
