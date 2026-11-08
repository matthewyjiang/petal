from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from petal.identity import pip_name
from petal.models import Dep, ResolvedDep, Source
from petal.resolve.base import Runner, default_runner, dep_requirement, venv_python
from petal.system import SystemView


class PipCompileError(RuntimeError):
    """uv could not resolve the requirements; the message is uv's explanation."""


@dataclass(frozen=True)
class Pin:
    """One line of `uv pip compile` output."""

    name: str  # canonical distribution name
    version: str  # "" for direct references such as `pkg @ git+https://...`
    requirement: str  # the line itself, ready for `uv pip install`


class PipResolver:
    """Resolves deps on PyPI with `uv pip compile`, pinned to the system's copies."""

    def __init__(
        self, venv: Path, system: SystemView, runner: Runner = default_runner
    ) -> None:
        self.venv = venv
        self.system = system
        self.runner = runner
        # Requirement -> why uv could not resolve it, for error reporting.
        self.failures: dict[str, str] = {}

    def resolve(self, dep: Dep) -> ResolvedDep | None:
        requirement = dep_requirement(dep)
        try:
            pins = compile_requirements(
                [requirement], self.venv, self.system, self.runner
            )
        except PipCompileError as exc:
            self.failures[requirement] = str(exc)
            return None
        key = pip_name(dep.name)
        version = next((pin.version for pin in pins if pin.name == key), "")
        return ResolvedDep(dep=dep, chosen_source=Source.PIP, resolved_version=version)


def compile_requirements(
    requirements: list[str], venv: Path, system: SystemView, runner: Runner
) -> list[Pin]:
    """Resolve requirements and their whole dependency closure, honoring system pins."""
    cmd = ["uv", "pip", "compile", "--python", str(venv_python(venv))]
    constraints = system.constraints_file()
    if constraints is not None:
        cmd += ["--constraints", str(constraints)]
    cmd += ["--no-header", "--no-annotate", "-"]
    proc = runner(cmd, input="".join(f"{req}\n" for req in requirements))
    if proc.returncode != 0:
        raise PipCompileError((proc.stderr or "uv pip compile failed").strip())
    return parse_pins(proc.stdout)


_PIN_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;]+)")
_DIRECT_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*@")


def parse_pins(output: str) -> list[Pin]:
    pins: list[Pin] = []
    for raw in output.splitlines():
        line = raw.split(" #", 1)[0].strip()
        if not line or line.startswith(("#", "-")):
            continue
        if match := _PIN_RE.match(line):
            pins.append(Pin(pip_name(match.group(1)), match.group(2), line))
        elif match := _DIRECT_RE.match(line):
            pins.append(Pin(pip_name(match.group(1)), "", line))
    return pins
