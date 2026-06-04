from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib

from packaging.utils import canonicalize_name

from petal.config import find_workspace_root
from petal.discover.package_xml import package_name, parse_package_xml
from petal.discover.pyproject import parse_pyproject
from petal.discover.setup_cfg import parse_setup_cfg, parse_setup_py
from petal.models import Dep, Source


@dataclass
class WorkspaceDiscovery:
    deps: list[Dep]
    by_package: dict[str, list[Dep]] = field(default_factory=dict)


def _has_colcon_ignore(path: Path, stop_at: Path) -> bool:
    for current in (path, *path.parents):
        if current == stop_at.parent:
            break
        if (current / "COLCON_IGNORE").exists():
            return True
        if current == stop_at:
            break
    return False


def _load_overrides(workspace_root: Path) -> dict[str, dict[str, str]]:
    manifest = workspace_root / "petal.toml"
    if not manifest.exists():
        return {}
    data = tomllib.loads(manifest.read_text(encoding="utf-8"))
    return data.get("overrides", {}) or {}


def _apply_overrides(deps: list[Dep], overrides: dict[str, dict[str, str]]) -> list[Dep]:
    out: list[Dep] = []
    for dep in deps:
        override = overrides.get(dep.name)
        if override and "pip" in override:
            out.append(
                Dep(
                    name=canonicalize_name(override["pip"]),
                    version_spec=dep.version_spec,
                    source_hint=Source.PIP,
                    origin_packages=list(dep.origin_packages),
                )
            )
        elif override and "apt" in override:
            out.append(
                Dep(
                    name=override["apt"],
                    version_spec=dep.version_spec,
                    source_hint=Source.APT,
                    origin_packages=list(dep.origin_packages),
                )
            )
        else:
            out.append(dep)
    return out


def _merge_deps(deps: list[Dep]) -> list[Dep]:
    merged: dict[str, Dep] = {}
    for dep in deps:
        key = canonicalize_name(dep.name) if dep.source_hint == Source.PIP else dep.name
        existing = merged.get(key)
        if existing is None:
            merged[key] = Dep(
                name=key,
                version_spec=dep.version_spec,
                source_hint=dep.source_hint,
                origin_packages=list(dict.fromkeys(dep.origin_packages)),
            )
            continue

        specs = [s for s in (existing.version_spec, dep.version_spec) if s]
        existing.version_spec = ",".join(dict.fromkeys(specs))
        existing.origin_packages = list(
            dict.fromkeys([*existing.origin_packages, *dep.origin_packages])
        )
        if existing.source_hint != dep.source_hint and dep.source_hint == Source.PIP:
            existing.source_hint = Source.PIP
    return sorted(merged.values(), key=lambda d: d.name)


def discover_workspace(start: Path | None = None) -> WorkspaceDiscovery:
    workspace_root = find_workspace_root(start)
    src = workspace_root / "src"
    if not src.is_dir():
        return WorkspaceDiscovery(deps=[], by_package={})

    overrides = _load_overrides(workspace_root)
    by_package: dict[str, list[Dep]] = {}
    all_deps: list[Dep] = []

    for package_xml in sorted(src.rglob("package.xml")):
        package_dir = package_xml.parent
        if _has_colcon_ignore(package_dir, src):
            continue
        origin = package_name(package_xml)
        deps = parse_package_xml(package_xml)
        if (package_dir / "setup.cfg").exists():
            deps.extend(parse_setup_cfg(package_dir / "setup.cfg", origin))
        if (package_dir / "setup.py").exists():
            deps.extend(parse_setup_py(package_dir / "setup.py", origin))
        if (package_dir / "pyproject.toml").exists():
            deps.extend(parse_pyproject(package_dir / "pyproject.toml", origin))
        deps = _apply_overrides(deps, overrides)
        by_package[origin] = deps
        all_deps.extend(deps)

    return WorkspaceDiscovery(deps=_merge_deps(all_deps), by_package=by_package)
