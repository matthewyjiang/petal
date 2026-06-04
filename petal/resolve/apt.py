from __future__ import annotations

from petal.models import Dep, ResolvedDep, Source
from petal.resolve.base import Runner, default_runner, python_apt_name


class AptResolver:
    def __init__(self, runner: Runner = default_runner) -> None:
        self.runner = runner

    def can_resolve(self, dep: Dep) -> bool:
        return self.resolve(dep) is not None

    def resolve(self, dep: Dep) -> ResolvedDep | None:
        apt_pkg = python_apt_name(dep.name)
        proc = self.runner(["apt-cache", "policy", apt_pkg])
        if proc.returncode != 0:
            return None
        version = _candidate_version(proc.stdout)
        if not version:
            return None
        return ResolvedDep(
            dep=dep,
            chosen_source=Source.APT,
            resolved_version=version,
            apt_pkg=apt_pkg,
        )


def _candidate_version(output: str) -> str:
    for line in output.splitlines():
        text = line.strip()
        if not text.startswith("Candidate:"):
            continue
        version = text.split(":", 1)[1].strip()
        if version != "(none)":
            return version
    return ""
