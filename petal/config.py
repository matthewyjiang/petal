from __future__ import annotations

import hashlib
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib

from petal.models import Dep, Lock, Manifest, ResolvedDep, Source


def find_workspace_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for path in (current, *current.parents):
        if (path / "petal.toml").exists() or (path / "src").is_dir():
            return path
    return current


def write_manifest(path: Path, *, ros_distro: str, python_version: str) -> None:
    path.write_text(
        "[workspace]\n"
        f'ros_distro = "{ros_distro}"\n'
        f'python_version = "{python_version}"\n'
        "\n"
        "[deps]\n"
        "\n"
        "[overrides]\n",
        encoding="utf-8",
    )


def manifest_hash(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def load_manifest(path: Path) -> Manifest:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    workspace = data.get("workspace", {})
    deps: list[Dep] = []
    for name, value in (data.get("deps", {}) or {}).items():
        if isinstance(value, str):
            deps.append(Dep(name=name, version_spec="" if value == "*" else value))
        elif isinstance(value, dict):
            if "pip" in value:
                spec = value.get("pip") or ""
                deps.append(
                    Dep(
                        name=name,
                        version_spec="" if spec == "*" else str(spec),
                        source_hint=Source.PIP,
                    )
                )
            elif "apt" in value:
                deps.append(
                    Dep(
                        name=str(value["apt"]),
                        source_hint=Source.APT,
                    )
                )
    return Manifest(
        ros_distro=str(workspace.get("ros_distro", "")),
        python_version=str(workspace.get("python_version", "")),
        deps=deps,
    )


def load_lock(path: Path) -> Lock:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    resolved: list[ResolvedDep] = []
    for item in data.get("resolved", []) or []:
        source = Source(str(item["source"]))
        dep = Dep(name=str(item["name"]))
        resolved.append(
            ResolvedDep(
                dep=dep,
                chosen_source=source,
                resolved_version=str(item.get("version", "")),
                apt_pkg=str(item.get("apt_pkg", "")),
            )
        )
    return Lock(manifest_hash=str(data.get("manifest_hash", "")), resolved=resolved)
