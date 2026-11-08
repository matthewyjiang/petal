"""Dependency resolution: pick a source for every dep, then pin the PyPI ones."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path

from petal.identity import dep_key, lock_key, pip_name
from petal.models import Dep, ResolvedDep, Source
from petal.planner import PlannerConflict, check_version_conflicts
from petal.resolve.apt import AptResolver
from petal.resolve.base import Runner, default_runner, dep_requirement
from petal.resolve.distro import DistroResolver
from petal.resolve.pip import (
    Pin,
    PipCompileError,
    compile_requirements,
    venv_versions,
)
from petal.resolve.rosdep import RosdepResolver
from petal.system import SystemView

# Rosdep and apt-cache lookups are subprocess-bound; this caps concurrent ones.
_WORKERS = 8


@dataclass(frozen=True)
class Unresolved:
    dep: Dep
    reason: str = ""


class UnresolvedDependencies(RuntimeError):
    """Raised when workspace deps cannot be resolved from any allowed source."""

    def __init__(self, failures: list[Unresolved]) -> None:
        self.failures = failures
        lines = [f"could not resolve {len(failures)} dependencies:"]
        for failure in failures:
            dep = failure.dep
            origins = ", ".join(dep.origin_packages) or "petal.toml"
            lines.append(f"  {dep.name}{dep.version_spec} (from {origins})")
            lines.extend(f"      {line}" for line in failure.reason.splitlines())
        if any(f.dep.source_hint == Source.ROSDEP for f in failures):
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
        locked: dict[str, str] | None = None,
        runner: Runner = default_runner,
    ) -> None:
        """`locked` maps PyPI names to versions in the current lock, if any."""
        self.locked = locked or {}
        self.venv = venv
        self.system = system
        self.runner = runner
        self.distro = DistroResolver(system)
        self.rosdep = RosdepResolver(ros_distro, runner)
        self.apt = AptResolver(runner)

    def resolve_all(self, deps: list[Dep]) -> list[ResolvedDep]:
        """Resolve every dep, pinning PyPI ones as one consistent set.

        Raises UnresolvedDependencies or PlannerConflict before anything is
        installed, so callers can validate a whole workspace up front.
        """
        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            outcomes = list(pool.map(self._select, deps))
        failures = [item for item in outcomes if isinstance(item, Unresolved)]
        if failures:
            raise UnresolvedDependencies(failures)
        resolved = [item for item in outcomes if isinstance(item, ResolvedDep)]
        # Spec clashes between packages are reported with their origins before
        # uv would report them without.
        check_version_conflicts(resolved)
        return self._pin_pypi(resolved)

    # Changing these chains? Bump config._RESOLUTION_POLICY.
    def _select(self, dep: Dep) -> ResolvedDep | Unresolved:
        hint = dep.source_hint
        if hint == Source.DISTRO:
            return self.distro.resolve(dep) or Unresolved(dep)
        if hint == Source.APT:
            return self.apt.resolve(dep) or Unresolved(dep)
        if hint == Source.PIP:
            return self._select_python(dep)
        if hint == Source.ROSDEP:
            # rosdep keys are not PyPI names. Never guess one on PyPI: an unknown
            # key (typo, unreleased package, stale rosdep cache) would install
            # whatever happens to be published under that name.
            return self.distro.resolve(dep) or self._via_rosdep(dep) or Unresolved(dep)
        return (
            self.distro.resolve(dep)
            or self._via_rosdep(dep)
            or self.apt.resolve(dep)
            or self._select_python(dep)
        )

    def _via_rosdep(self, dep: Dep) -> ResolvedDep | Unresolved | None:
        resolved = self.rosdep.resolve(dep)
        if resolved and resolved.chosen_source == Source.PIP:
            # Rosdep `pip:` rules name real PyPI packages; give them the same
            # system check and pinning as any other Python requirement.
            return self._select_python(resolved.dep)
        return resolved

    def _select_python(self, dep: Dep) -> ResolvedDep | Unresolved:
        """System copy when it satisfies the spec, PyPI when the system lacks it."""
        if not self.system.protects(dep.name):
            return ResolvedDep(dep, Source.PIP)
        provided = self.distro.resolve(dep)
        if provided:
            return provided
        return Unresolved(
            dep,
            f"the system provides {dep.name} {self.system.version(dep.name)}, "
            f"which does not satisfy {dep.version_spec}; petal will not shadow it.\n"
            "to install a copy anyway, declare it under [deps] with "
            "`petal add --pip <name> <spec>`",
        )

    def _pin_pypi(self, resolved: list[ResolvedDep]) -> list[ResolvedDep]:
        """Resolve all PyPI deps together and record each top-level version."""
        items = [item for item in resolved if item.chosen_source == Source.PIP]
        if not items:
            return resolved
        # Keep what is locked or installed when still compatible.
        preferences = {**venv_versions(self.venv, self.runner), **self.locked}
        try:
            pins = self._compile([dep_requirement(i.dep) for i in items], preferences)
        except PipCompileError as joint:
            failures: list[Unresolved] = []
            for item in items:
                try:
                    self._compile([dep_requirement(item.dep)], preferences)
                except PipCompileError as exc:
                    failures.append(Unresolved(item.dep, str(exc)))
            if failures:
                raise UnresolvedDependencies(failures) from joint
            raise PlannerConflict(
                f"pip dependencies conflict with each other:\n{joint}"
            ) from joint
        versions = {pin.name: pin.version for pin in pins}
        return [
            replace(item, resolved_version=versions.get(pip_name(item.dep.name), ""))
            if item.chosen_source == Source.PIP
            else item
            for item in resolved
        ]

    def _compile(
        self, requirements: list[str], preferences: dict[str, str]
    ) -> list[Pin]:
        return compile_requirements(
            requirements, self.venv, self.system, self.runner, preferences
        )


def lock_mismatch(
    locked: list[ResolvedDep], deps: list[Dep], system: SystemView
) -> str:
    """Why a lock no longer fits this system, or "" when it still does.

    Checks the facts the lock relied on instead of comparing whole-system
    snapshots, so a committed lock stays valid on any machine that provides
    what it needs. Only declared deps are checked; locked PyPI pins are still
    resolved against the system constraints when installed.
    """
    entries = {lock_key(item): item for item in locked}
    distro = DistroResolver(system)
    for dep in deps:
        entry = entries.get(dep_key(dep))
        if entry is None:
            continue
        if entry.chosen_source == Source.DISTRO and not distro.resolve(dep):
            version = system.version(dep.name)
            found = f"has {version}" if version else "does not provide it"
            return (
                f"{dep.name}{dep.version_spec} is locked to the system, which {found}"
            )
        if entry.chosen_source == Source.PIP and system.protects(dep.name):
            return (
                f"{dep.name} is locked to PyPI, but the system now provides "
                f"{system.version(dep.name)}"
            )
    return ""
