"""Dependency resolvers."""

from __future__ import annotations

from pathlib import Path

from petal.models import Dep, ResolvedDep, Source
from petal.resolve.apt import AptResolver
from petal.resolve.base import Runner, default_runner
from petal.resolve.distro import DistroResolver
from petal.resolve.pip import PipResolver
from petal.resolve.rosdep import RosdepResolver


class UnresolvedDependencies(RuntimeError):
    """Raised when workspace deps cannot be resolved from any allowed source."""

    def __init__(self, deps: list[Dep]) -> None:
        self.deps = deps
        lines = [f"could not resolve {len(deps)} dependencies:"]
        for dep in deps:
            origins = ", ".join(dep.origin_packages) or "petal.toml"
            lines.append(f"  {dep.name}{dep.version_spec} (from {origins})")
        if any(dep.source_hint == Source.ROSDEP for dep in deps):
            lines.extend(
                [
                    "package.xml keys resolve only through rosdep, never PyPI.",
                    "run `rosdep update`, or map a key explicitly in petal.toml:",
                    "  [overrides]",
                    '  <key> = { pip = "<pypi-name>" }',
                ]
            )
        super().__init__("\n".join(lines))


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

    def preload(self) -> None:
        self.distro._modules()

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
            # rosdep keys are not PyPI names. Never guess one on PyPI: an unknown
            # key (typo, unreleased package, stale rosdep cache) would install
            # whatever happens to be published under that name. Rosdep's own
            # `pip:` rules still resolve to PIP via RosdepResolver.
            return [self.distro, self.rosdep]
        if hint == Source.APT:
            return [self.apt]
        if hint == Source.PIP:
            return [self.pip]
        return [self.distro, self.rosdep, self.apt, self.pip]
