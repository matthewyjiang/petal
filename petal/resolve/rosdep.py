from __future__ import annotations

from petal.models import Dep, ResolvedDep, Source
from petal.resolve.base import Runner, default_runner


class RosdepResolver:
    def __init__(self, ros_distro: str, runner: Runner = default_runner) -> None:
        self.ros_distro = ros_distro
        self.runner = runner

    def can_resolve(self, dep: Dep) -> bool:
        return self.resolve(dep) is not None

    def resolve(self, dep: Dep) -> ResolvedDep | None:
        proc = self.runner(
            ["rosdep", "resolve", dep.name, "--rosdistro", self.ros_distro]
        )
        if proc.returncode != 0:
            return None
        parsed = parse_rosdep_resolve(proc.stdout)
        if parsed.apt:
            return ResolvedDep(
                dep=dep,
                chosen_source=Source.APT,
                apt_pkg=parsed.apt[0],
            )
        if parsed.pip:
            pip_dep = Dep(
                name=parsed.pip[0],
                version_spec=dep.version_spec,
                source_hint=Source.PIP,
                origin_packages=list(dep.origin_packages),
            )
            return ResolvedDep(dep=pip_dep, chosen_source=Source.PIP)
        return None


class RosdepResult:
    def __init__(self) -> None:
        self.apt: list[str] = []
        self.pip: list[str] = []


def parse_rosdep_resolve(output: str) -> RosdepResult:
    result = RosdepResult()
    section = ""
    for line in output.splitlines():
        text = line.strip()
        if not text:
            continue
        if text.startswith("#"):
            section = text[1:].strip().lower()
            continue
        if section == "apt":
            result.apt.extend(text.split())
        elif section == "pip":
            result.pip.extend(text.split())
    return result
