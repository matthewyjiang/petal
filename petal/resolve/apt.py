from __future__ import annotations

from petal.identity import python_apt_package
from petal.models import Dep, ResolvedDep, Source
from petal.resolve.base import (
    Runner,
    default_runner,
    satisfies,
    upstream_version,
)


class AptResolver:
    def __init__(self, runner: Runner = default_runner) -> None:
        self.runner = runner

    def resolve(self, dep: Dep) -> ResolvedDep | None:
        apt_pkg = python_apt_package(dep.name)
        proc = self.runner(["apt-cache", "policy", apt_pkg])
        if proc.returncode != 0:
            return None
        version = _candidate_version(proc.stdout)
        if not version:
            return None
        if dep.version_spec and not satisfies(
            upstream_version(version), dep.version_spec
        ):
            # Fall through to later sources rather than install a deb that
            # does not meet the requirement.
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
