from __future__ import annotations

import re
from pathlib import Path

from petal.models import Dep, ResolvedDep, Source
from petal.resolve.base import (
    Runner,
    canonical,
    default_runner,
    dep_requirement,
    venv_python,
)


class PipResolver:
    def __init__(
        self, venv: Path, runner: Runner = default_runner, use_uv: bool = True
    ) -> None:
        self.venv = venv
        self.runner = runner
        self.use_uv = use_uv

    def can_resolve(self, dep: Dep) -> bool:
        return True

    def resolve(self, dep: Dep) -> ResolvedDep | None:
        requirement = dep_requirement(dep)
        if self.use_uv:
            proc = self.runner(
                [
                    "uv",
                    "pip",
                    "compile",
                    "--python",
                    str(venv_python(self.venv)),
                    "-",
                ],
                input=requirement,
            )
        else:
            proc = self.runner(
                [
                    str(venv_python(self.venv)),
                    "-m",
                    "pip",
                    "install",
                    "--dry-run",
                    requirement,
                ]
            )
        if proc.returncode != 0:
            return None
        version = parse_pip_version(dep.name, proc.stdout)
        return ResolvedDep(dep=dep, chosen_source=Source.PIP, resolved_version=version)


def parse_pip_version(name: str, output: str) -> str:
    normalized = re.escape(canonical(name)).replace("\\-", "[-_]")
    patterns = [
        re.compile(rf"^{normalized}==([^\s;]+)", re.IGNORECASE),
        re.compile(rf"Would install .*\b{normalized}-([^\s]+)", re.IGNORECASE),
    ]
    for line in output.splitlines():
        text = line.strip()
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                return match.group(1)
    return ""
