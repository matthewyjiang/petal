"""Dependency resolvers."""

from __future__ import annotations

from pathlib import Path

from petal.models import Dep, ResolvedDep, Source
from petal.resolve.apt import AptResolver
from petal.resolve.base import Runner, default_runner, dep_requirement
from petal.resolve.distro import DistroResolver
from petal.resolve.pip import PipResolver
from petal.resolve.rosdep import RosdepResolver
from petal.system import SystemView


class UnresolvedDependencies(RuntimeError):
    """Raised when workspace deps cannot be resolved from any allowed source."""

    def __init__(self, deps: list[Dep], reasons: dict[str, str] | None = None) -> None:
        self.deps = deps
        reasons = reasons or {}
        lines = [f"could not resolve {len(deps)} dependencies:"]
        for dep in deps:
            origins = ", ".join(dep.origin_packages) or "petal.toml"
            lines.append(f"  {dep.name}{dep.version_spec} (from {origins})")
            for line in reasons.get(dep.name, "").splitlines():
                lines.append(f"      {line.strip()}")
        if any(dep.source_hint == Source.ROSDEP for dep in deps):
            lines.extend(
                [
                    "package.xml keys resolve only through rosdep, never PyPI.",
                    "run `rosdep update`, or map the key in petal.toml:",
                    "  [overrides]",
                    '  <key> = { pip = "<pypi-name>" }   # or { apt = "<apt-package>" }',
                    "  <key> = { skip = true }           # not needed on this system",
                ]
            )
        super().__init__("\n".join(lines))


class ResolutionManager:
    def __init__(
        self,
        *,
        ros_distro: str,
        venv: Path,
        system: SystemView,
        runner: Runner = default_runner,
    ) -> None:
        self.cache: dict[tuple[str, str, Source | None], ResolvedDep | None] = {}
        self.system = system
        self.distro = DistroResolver(system)
        self.rosdep = RosdepResolver(ros_distro, runner)
        self.apt = AptResolver(runner)
        self.pip = PipResolver(venv, system, runner)

    def resolve(self, dep: Dep) -> ResolvedDep | None:
        key = (dep.name, dep.version_spec, dep.source_hint)
        if key not in self.cache:
            self.cache[key] = self._resolve(dep)
        return self.cache[key]

    def failure_reason(self, dep: Dep) -> str:
        """Explain why `dep` did not resolve, as far as petal knows."""
        lines: list[str] = []
        version = self.system.version(dep.name)
        if version and self.system.protects(dep.name):
            lines.append(
                f"the system provides {dep.name} {version}; petal will not shadow "
                "it in .petal/venv (`petal add --pip` installs a copy anyway)"
            )
        detail = self.pip.failures.get(dep_requirement(dep))
        if detail:
            lines.append(detail)
        return "\n".join(lines)

    # Changing these chains? Bump config._RESOLUTION_POLICY.
    def _resolve(self, dep: Dep) -> ResolvedDep | None:
        hint = dep.source_hint
        if hint == Source.DISTRO:
            return self.distro.resolve(dep)
        if hint == Source.APT:
            return self.apt.resolve(dep)
        if hint == Source.PIP:
            return self._resolve_python(dep)
        if hint == Source.ROSDEP:
            # rosdep keys are not PyPI names. Never guess one on PyPI: an unknown
            # key (typo, unreleased package, stale rosdep cache) would install
            # whatever happens to be published under that name.
            return self.distro.resolve(dep) or self._via_rosdep(dep)
        return (
            self.distro.resolve(dep)
            or self._via_rosdep(dep)
            or self.apt.resolve(dep)
            or self._resolve_python(dep)
        )

    def _via_rosdep(self, dep: Dep) -> ResolvedDep | None:
        resolved = self.rosdep.resolve(dep)
        if resolved and resolved.chosen_source == Source.PIP:
            # Rosdep `pip:` rules name real PyPI packages; give them the same
            # system check and version pinning as any other Python requirement.
            return self._resolve_python(resolved.dep)
        return resolved

    def _resolve_python(self, dep: Dep) -> ResolvedDep | None:
        """System copy first, PyPI otherwise, unless the user asked to shadow it."""
        if self.system.protects(dep.name):
            provided = self.distro.resolve(dep)
            if provided:
                return provided
        return self.pip.resolve(dep)
