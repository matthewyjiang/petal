from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

import tomlkit
from tomlkit.toml_document import TOMLDocument

from petal.identity import dep_key as canonical_dep_key
from petal.identity import pip_name, python_apt_package

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib

from petal.models import Dep, Lock, LockStamp, Manifest, ResolvedDep, Source


def find_workspace_root(start: Path | None = None) -> Path:
    """The workspace containing `start` (default: cwd).

    The nearest ancestor with petal.toml, like git or cargo. Without one, the
    nearest ancestor with a `src/` directory that is not itself a ROS package:
    ament_cmake packages have their own `src/`.
    """
    current = (start or Path.cwd()).resolve()
    ancestors = (current, *current.parents)
    for path in ancestors:
        if (path / "petal.toml").is_file():
            return path
    for path in ancestors:
        if (path / "src").is_dir() and not (path / "package.xml").is_file():
            return path
    return current


def write_manifest(path: Path, *, ros_distro: str) -> None:
    doc = tomlkit.document()
    doc["workspace"] = {"ros_distro": ros_distro}
    doc["deps"] = tomlkit.table()
    doc["overrides"] = tomlkit.table()
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def add_manifest_dep(
    path: Path,
    name: str,
    *,
    version_spec: str = "",
    source_hint: Source | None = None,
    apt_pkg: str = "",
) -> None:
    """Add or update `name` in [deps], keeping the rest of the file as written.

    An existing entry whose name differs only by PEP 503 normalization is
    updated in place under its original spelling.
    """
    doc = _load_document(path)
    deps = doc.setdefault("deps", tomlkit.table())
    key = _manifest_key(deps, name) or name
    spec = version_spec or "*"
    if source_hint == Source.PIP:
        value = tomlkit.inline_table()
        value["pip"] = spec
    elif source_hint == Source.APT:
        value = tomlkit.inline_table()
        value["apt"] = apt_pkg or python_apt_package(name)
    else:
        value = spec
    deps[key] = value
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def remove_manifest_dep(path: Path, name: str) -> bool:
    """Remove `name` (matched by PEP 503 name) from [deps]; False if absent."""
    doc = _load_document(path)
    deps = doc.get("deps")
    key = _manifest_key(deps, name) if deps is not None else None
    if deps is None or key is None:
        return False
    del deps[key]
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return True


def manifest_has_dep(path: Path, name: str) -> bool:
    """True when [deps] has `name`, matched by PEP 503 name."""
    deps = _load_document(path).get("deps")
    return deps is not None and _manifest_key(deps, name) is not None


def _load_document(path: Path) -> TOMLDocument:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return tomlkit.parse(text)


def _manifest_key(deps: Mapping[str, object], name: str) -> str | None:
    key = pip_name(name)
    return next((existing for existing in deps if pip_name(existing) == key), None)


def lock_stamp(manifest_path: Path, deps: list[Dep]) -> LockStamp:
    """Stamp for a lock resolved from this manifest and these (input) deps."""
    manifest = manifest_hash(manifest_path) if manifest_path.exists() else ""
    return LockStamp(manifest, dependency_hash(deps))


def manifest_hash(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


# Bump when resolution rules change so `petal sync` stops reusing locks that
# were resolved under the old rules. 2: rosdep keys no longer fall back to PyPI.
# 3: Python requirements the ROS/system Python provides resolve to distro.
# 4: the lock's dependency_hash covers the input deps, not the resolved ones.
# 5: lock entries record their declared spec and hint.
# 6: apt candidates must satisfy the declared version spec.
# 7: the lock pins the whole PyPI closure, not just declared deps.
_RESOLUTION_POLICY = "7"


def dependency_hash(deps: list[Dep]) -> str:
    lines = [f"policy\t{_RESOLUTION_POLICY}"]
    for dep in sorted(
        deps,
        key=lambda item: (
            canonical_dep_key(item),
            item.version_spec,
            item.source_hint.value if item.source_hint else "",
        ),
    ):
        source = dep.source_hint.value if dep.source_hint else ""
        origins = ",".join(sorted(dep.origin_packages))
        lines.append(
            f"{canonical_dep_key(dep)}\t{dep.version_spec}\t{source}\t{origins}"
        )
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
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
        deps=deps,
    )


def load_lock_or_none(path: Path) -> Lock | None:
    """Load petal.lock, or return None when it is missing or unreadable.

    Callers treat an unusable lock as absent and re-resolve.
    """
    if not path.exists():
        return None
    try:
        return load_lock(path)
    except (OSError, ValueError, KeyError, TypeError):
        # ValueError covers TOMLDecodeError and unknown sources; KeyError and
        # TypeError cover entries missing fields or with the wrong shape.
        return None


def load_lock(path: Path) -> Lock:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    resolved: list[ResolvedDep] = []
    for item in data.get("resolved", []) or []:
        source = Source(str(item["source"]))
        hint = str(item.get("hint", ""))
        dep = Dep(
            name=str(item["name"]),
            version_spec=str(item.get("spec", "")),
            source_hint=Source(hint) if hint else None,
        )
        resolved.append(
            ResolvedDep(
                dep=dep,
                chosen_source=source,
                resolved_version=str(item.get("version", "")),
                apt_pkg=str(item.get("apt_pkg", "")),
                transitive=bool(item.get("transitive", False)),
            )
        )
    return Lock(
        manifest_hash=str(data.get("manifest_hash", "")),
        resolved=resolved,
        dependency_hash=str(data.get("dependency_hash", "")),
    )
