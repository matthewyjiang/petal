from __future__ import annotations

from packaging.utils import canonicalize_name

from petal.models import Dep, ResolvedDep, Source


def pip_name(name: str) -> str:
    """Return the canonical Python distribution identity (PEP 503)."""
    return canonicalize_name(name)


def apt_package(name: str) -> str:
    """Return the stable identity for an apt package name.

    Apt package names are already hyphen-oriented and case-insensitive in
    practice; keep this path explicit so callers do not accidentally use a
    Python-only normalization rule for system package identity.
    """
    return name.strip().lower().replace("_", "-")


def python_apt_package(name: str) -> str:
    value = apt_package(name)
    if value.startswith("python3-"):
        return value
    return f"python3-{value}"


def source_hint(source: Source | None) -> str:
    return source.value if source else ""


def version_spec(spec: str) -> str:
    return spec.strip()


def dep_key(dep: Dep) -> str:
    if dep.source_hint == Source.APT:
        return apt_package(dep.name)
    return pip_name(dep.name)


def resolved_key(item: ResolvedDep) -> str:
    if item.apt_pkg:
        return apt_package(item.apt_pkg)
    return dep_key(item.dep)


def lock_key(item: ResolvedDep) -> str:
    if item.chosen_source == Source.APT and item.apt_pkg:
        return apt_package(item.apt_pkg)
    return dep_key(item.dep)
