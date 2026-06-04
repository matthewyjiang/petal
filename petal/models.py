from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Source(str, Enum):
    DISTRO = "distro"
    APT = "apt"
    ROSDEP = "rosdep"
    PIP = "pip"


@dataclass
class Dep:
    name: str
    version_spec: str = ""
    source_hint: Source | None = None
    origin_packages: list[str] = field(default_factory=list)


@dataclass
class ResolvedDep:
    dep: Dep
    chosen_source: Source
    resolved_version: str = ""
    apt_pkg: str = ""
    transitive: bool = False


@dataclass
class Manifest:
    ros_distro: str
    python_version: str
    deps: list[Dep]


@dataclass
class Lock:
    manifest_hash: str
    resolved: list[ResolvedDep]
