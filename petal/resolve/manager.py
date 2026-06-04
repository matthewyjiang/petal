from __future__ import annotations

from pathlib import Path

from petal.models import Dep, ResolvedDep, Source
from petal.resolve.apt import AptResolver
from petal.resolve.base import Runner, default_runner
from petal.resolve.distro import DistroResolver
from petal.resolve.pip import PipResolver
from petal.resolve.rosdep import RosdepResolver


class ResolutionManager:
    def __init__(
        self,
        *,
        ros_distro: str,
        venv: Path,
        modules: set[str] | None = None,
        runner: Runner = default_runner,
    ) -> None:
        self.cache: dict[tuple[str, str, Source | None], ResolvedDep | None] = {}
        self.distro = DistroResolver(ros_distro, modules)
        self.rosdep = RosdepResolver(ros_distro, runner)
        self.apt = AptResolver(runner)
        self.pip = PipResolver(venv, runner)

    def resolve(self, dep: Dep) -> ResolvedDep | None:
        key = (dep.name, dep.version_spec, dep.source_hint)
        if key in self.cache:
            return self.cache[key]

        resolvers = self._resolvers(dep.source_hint)
        for resolver in resolvers:
            resolved = resolver.resolve(dep)
            if resolved:
                self.cache[key] = resolved
                return resolved
        self.cache[key] = None
        return None

    def _resolvers(self, hint: Source | None):
        if hint == Source.DISTRO:
            return [self.distro]
        if hint == Source.ROSDEP:
            return [self.distro, self.rosdep, self.pip]
        if hint == Source.APT:
            return [self.apt]
        if hint == Source.PIP:
            return [self.pip]
        return [self.distro, self.rosdep, self.apt, self.pip]
