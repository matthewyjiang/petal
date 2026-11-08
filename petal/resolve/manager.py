"""Dependency resolution: pick a source for every dep, then pin the PyPI ones."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from petal.identity import pip_name, python_apt_package
from petal.models import Dep, ResolvedDep, Source
from petal.planner import PlannerConflict
from petal.resolve.apt import AptResolver
from petal.resolve.base import Runner, default_runner, dep_requirement
from petal.resolve.distro import DistroResolver
from petal.resolve.pip import Pin, PipCompileError, compile_requirements
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
        runner: Runner = default_runner,
    ) -> None:
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
        # Identical deps (same name, spec and hint) share one lookup and result.
        unique = list({_dep_id(dep): dep for dep in deps}.values())
        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            selected = dict(zip(map(_dep_id, unique), pool.map(self._select, unique)))
        outcomes = [selected[_dep_id(dep)] for dep in deps]
        failures = [item for item in outcomes if isinstance(item, Unresolved)]
        if failures:
            raise UnresolvedDependencies(failures)
        resolved = [item for item in outcomes if isinstance(item, ResolvedDep)]
        resolved = self._defer_to_planned_apt(resolved)
        self._pin_pypi(resolved)
        return resolved

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

    def _defer_to_planned_apt(self, resolved: list[ResolvedDep]) -> list[ResolvedDep]:
        """Let apt provide a Python requirement it is about to install anyway.

        Common in ROS: package.xml depends on `python3-scipy` while setup.py asks
        for `scipy`. Installing both would shadow the deb with a PyPI copy.
        """
        apt_pkgs = {
            item.apt_pkg for item in resolved if item.chosen_source == Source.APT
        }
        return [
            ResolvedDep(item.dep, Source.DISTRO)
            if item.chosen_source == Source.PIP
            and python_apt_package(item.dep.name) in apt_pkgs
            and pip_name(item.dep.name) not in self.system.allow_shadow
            else item
            for item in resolved
        ]

    def _pin_pypi(self, resolved: list[ResolvedDep]) -> None:
        """Resolve all PyPI deps together and record each top-level version."""
        items = [item for item in resolved if item.chosen_source == Source.PIP]
        if not items:
            return
        try:
            pins = self._compile([dep_requirement(item.dep) for item in items])
        except PipCompileError as joint:
            failures: list[Unresolved] = []
            for item in items:
                try:
                    self._compile([dep_requirement(item.dep)])
                except PipCompileError as exc:
                    failures.append(Unresolved(item.dep, str(exc)))
            if failures:
                raise UnresolvedDependencies(failures) from joint
            raise PlannerConflict(
                f"pip dependencies conflict with each other:\n{joint}"
            ) from joint
        versions = {pin.name: pin.version for pin in pins}
        for item in items:
            item.resolved_version = versions.get(pip_name(item.dep.name), "")

    def _compile(self, requirements: list[str]) -> list[Pin]:
        return compile_requirements(requirements, self.venv, self.system, self.runner)


def _dep_id(dep: Dep) -> tuple[str, str, Source | None]:
    return (dep.name, dep.version_spec, dep.source_hint)
