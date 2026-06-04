from __future__ import annotations

from dataclasses import dataclass, field

from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from petal.models import ResolvedDep, Source


class PlannerConflict(RuntimeError):
    pass


@dataclass
class Plan:
    distro: list[ResolvedDep] = field(default_factory=list)
    apt: list[ResolvedDep] = field(default_factory=list)
    pip: list[ResolvedDep] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Bounds:
    exact: set[Version] = field(default_factory=set)
    excluded: set[Version] = field(default_factory=set)
    lower: Version | None = None
    lower_inclusive: bool = True
    upper: Version | None = None
    upper_inclusive: bool = True


def build_plan(resolved: list[ResolvedDep]) -> Plan:
    _check_version_conflicts(resolved)
    plan = Plan()

    for dep in resolved:
        if dep.chosen_source == Source.DISTRO:
            plan.distro.append(dep)
        elif dep.chosen_source in {Source.APT, Source.ROSDEP}:
            plan.apt.append(dep)
        elif dep.chosen_source == Source.PIP:
            plan.pip.append(dep)

    plan.warnings.extend(_shadow_warnings(resolved))
    plan.apt.sort(key=lambda item: item.apt_pkg or _key(item))
    plan.pip.sort(key=_key)
    plan.distro.sort(key=_key)
    return plan


def _check_version_conflicts(resolved: list[ResolvedDep]) -> None:
    by_name: dict[str, list[ResolvedDep]] = {}
    for item in resolved:
        by_name.setdefault(_key(item), []).append(item)

    for name, items in by_name.items():
        specs = [item.dep.version_spec for item in items if item.dep.version_spec]
        if len(specs) < 2:
            continue
        if not specs_compatible(specs):
            origins = _origin_summary(items)
            raise PlannerConflict(f"conflicting version specs for {name}: {origins}")


def specs_compatible(specs: list[str]) -> bool:
    combined = SpecifierSet(",".join(specs))
    bounds = _bounds_for(specs)

    if bounds.exact:
        allowed = [version for version in bounds.exact if combined.contains(version, prereleases=True)]
        return bool(allowed)

    if bounds.lower and bounds.upper:
        if bounds.lower > bounds.upper:
            return False
        if bounds.lower == bounds.upper and not (bounds.lower_inclusive and bounds.upper_inclusive):
            return False

    return True


def _bounds_for(specs: list[str]) -> _Bounds:
    bounds = _Bounds()
    for spec in SpecifierSet(",".join(specs)):
        version = Version(spec.version)
        op = spec.operator
        if op in {"==", "==="} and not spec.version.endswith(".*"):
            bounds.exact.add(version)
        elif op == "!=":
            bounds.excluded.add(version)
        elif op in {">", ">="}:
            inclusive = op == ">="
            if bounds.lower is None or version > bounds.lower:
                bounds.lower = version
                bounds.lower_inclusive = inclusive
            elif version == bounds.lower:
                bounds.lower_inclusive = bounds.lower_inclusive and inclusive
        elif op in {"<", "<="}:
            inclusive = op == "<="
            if bounds.upper is None or version < bounds.upper:
                bounds.upper = version
                bounds.upper_inclusive = inclusive
            elif version == bounds.upper:
                bounds.upper_inclusive = bounds.upper_inclusive and inclusive
    return bounds


def _shadow_warnings(resolved: list[ResolvedDep]) -> list[str]:
    by_name: dict[str, list[ResolvedDep]] = {}
    for item in resolved:
        by_name.setdefault(_key(item), []).append(item)

    warnings: list[str] = []
    for name, items in by_name.items():
        pip_items = [item for item in items if item.chosen_source == Source.PIP]
        system_items = [item for item in items if item.chosen_source in {Source.APT, Source.DISTRO}]
        if not pip_items or not system_items:
            continue
        specs = [item.dep.version_spec for item in items if item.dep.version_spec]
        if specs and not specs_compatible(specs):
            warnings.append(
                f"{name} requested via pip and system source with incompatible specs; apt/distro wins to avoid shadowing"
            )
        else:
            warnings.append(
                f"{name} requested via pip and system source; apt/distro wins by default to avoid shadowing"
            )
    return warnings


def _key(item: ResolvedDep) -> str:
    return canonicalize_name(item.dep.name)


def _origin_summary(items: list[ResolvedDep]) -> str:
    parts: list[str] = []
    for item in items:
        spec = item.dep.version_spec or "*"
        origins = ",".join(item.dep.origin_packages) or "unknown"
        parts.append(f"{origins} needs {item.dep.name}{spec}")
    return "; ".join(parts)
