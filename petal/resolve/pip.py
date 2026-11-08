"""PyPI resolution through `uv pip compile`, always pinned to the system's copies."""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from petal.identity import pip_name
from petal.resolve.base import Runner, venv_python
from petal.system import SystemView


class PipCompileError(RuntimeError):
    """uv could not resolve the requirements; the message is uv's explanation."""


@dataclass(frozen=True)
class Pin:
    """One line of `uv pip compile` output."""

    name: str  # canonical distribution name
    version: str  # "" for direct references such as `pkg @ git+https://...`
    requirement: str  # the line itself, ready for `uv pip install`


def compile_requirements(
    requirements: list[str],
    venv: Path,
    system: SystemView,
    runner: Runner,
    preferences: dict[str, str] | None = None,
) -> list[Pin]:
    """Resolve requirements and their whole dependency closure.

    System distributions are hard constraints. `preferences` (name -> version,
    e.g. locked or installed versions) are kept when still compatible, so
    adding one dependency does not upgrade everything else.
    """
    with tempfile.TemporaryDirectory(prefix="petal-") as tmp:
        # uv treats an existing output file as version preferences.
        output = Path(tmp) / "pins.txt"
        output.write_text(
            "".join(f"{n}=={v}\n" for n, v in sorted((preferences or {}).items()) if v),
            encoding="utf-8",
        )
        cmd = [
            *("uv", "pip", "compile", "--python", str(venv_python(venv))),
            *system.constraint_args(),
            *("--quiet", "--no-header", "--no-annotate", "--output-file", str(output)),
            "-",
        ]
        proc = runner(cmd, input="".join(f"{req}\n" for req in requirements))
        if proc.returncode != 0:
            raise PipCompileError((proc.stderr or "uv pip compile failed").strip())
        return parse_pins(output.read_text(encoding="utf-8"))


def venv_versions(venv: Path, runner: Runner) -> dict[str, str]:
    """Distributions installed in the venv itself (canonical name -> version)."""
    proc = runner(
        ["uv", "pip", "list", "--python", str(venv_python(venv)), "--format", "json"]
    )
    if proc.returncode != 0:
        proc = runner([str(venv_python(venv)), "-m", "pip", "list", "--format", "json"])
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return {}
    return {pip_name(str(item["name"])): str(item["version"]) for item in data}


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
