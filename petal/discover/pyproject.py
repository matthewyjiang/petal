from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib

from petal.discover.setup_cfg import _dep_from_requirement
from petal.models import Dep


def parse_pyproject(pyproject: Path, origin: str) -> list[Dep]:
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    deps: list[Dep] = []

    for raw in project.get("dependencies", []) or []:
        dep = _dep_from_requirement(raw, origin)
        if dep:
            deps.append(dep)

    optional = project.get("optional-dependencies", {}) or {}
    for requirements in optional.values():
        for raw in requirements or []:
            dep = _dep_from_requirement(raw, origin)
            if dep:
                deps.append(dep)
    return deps
