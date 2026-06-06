from __future__ import annotations

import hashlib
import re
from pathlib import Path

from packaging.utils import canonicalize_name

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib

from petal.models import Dep, Lock, Manifest, ResolvedDep, Source


_SECTION_RE = re.compile(r"^\s*\[[^\]]+\]\s*(?:#.*)?$")
_KEY_RE = re.compile(r"^\s*(?P<key>[A-Za-z0-9_-]+|\"[^\"]+\")\s*=")


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


def add_manifest_dep(
    path: Path,
    name: str,
    *,
    version_spec: str = "",
    source_hint: Source | None = None,
    apt_pkg: str = "",
) -> None:
    lines = _manifest_lines(path)
    start, end = _deps_span(lines)
    entry = _render_dep_entry(name, version_spec, source_hint, apt_pkg)
    key = _dep_key(name)

    for index in range(start, end):
        if _line_key(lines[index]) == key:
            lines[index] = _render_dep_entry(_raw_line_key(lines[index]) or name, version_spec, source_hint, apt_pkg)
            _write_manifest_lines(path, lines)
            return

    insert_at = end
    while insert_at > start and not lines[insert_at - 1].strip():
        insert_at -= 1
    lines.insert(insert_at, entry)
    _write_manifest_lines(path, lines)


def remove_manifest_dep(path: Path, name: str) -> bool:
    lines = _manifest_lines(path)
    start, end = _deps_span(lines)
    key = _dep_key(name)
    for index in range(start, end):
        if _line_key(lines[index]) == key:
            del lines[index]
            _write_manifest_lines(path, lines)
            return True
    return False


def manifest_hash(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def dependency_hash(deps: list[Dep]) -> str:
    lines = []
    for dep in sorted(deps, key=lambda item: (_dep_key(item.name), item.version_spec, item.source_hint.value if item.source_hint else "")):
        source = dep.source_hint.value if dep.source_hint else ""
        origins = ",".join(sorted(dep.origin_packages))
        lines.append(f"{_dep_key(dep.name)}\t{dep.version_spec}\t{source}\t{origins}")
    digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _manifest_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return text.splitlines()


def _write_manifest_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _deps_span(lines: list[str]) -> tuple[int, int]:
    for index, line in enumerate(lines):
        if line.strip() == "[deps]":
            start = index + 1
            end = len(lines)
            for next_index in range(start, len(lines)):
                if _SECTION_RE.match(lines[next_index]):
                    end = next_index
                    break
            return start, end

    if lines and lines[-1].strip():
        lines.append("")
    lines.append("[deps]")
    return len(lines), len(lines)


def _render_dep_entry(
    name: str,
    version_spec: str,
    source_hint: Source | None,
    apt_pkg: str,
) -> str:
    key = _toml_key(name)
    spec = version_spec or "*"
    if source_hint == Source.PIP:
        return f'{key} = {{ pip = "{_escape_toml_string(spec)}" }}'
    if source_hint == Source.APT:
        pkg = apt_pkg or _python_apt_name(name)
        return f'{key} = {{ apt = "{_escape_toml_string(pkg)}" }}'
    return f'{key} = "{_escape_toml_string(spec)}"'


def _line_key(line: str) -> str:
    key = _raw_line_key(line)
    return _dep_key(key) if key else ""


def _raw_line_key(line: str) -> str:
    match = _KEY_RE.match(line)
    if not match:
        return ""
    key = match.group("key")
    if key.startswith('"') and key.endswith('"'):
        key = key[1:-1]
    return key


def _dep_key(name: str) -> str:
    return canonicalize_name(name.replace("_", "-"))


def _toml_key(name: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]+", name):
        return name
    return f'"{_escape_toml_string(name)}"'


def _escape_toml_string(value: str) -> str:
    return value.replace('\\', '\\\\').replace('"', '\\"')


def _python_apt_name(name: str) -> str:
    value = _dep_key(name)
    if value.startswith("python3-"):
        return value
    return f"python3-{value}"


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
    return Lock(
        manifest_hash=str(data.get("manifest_hash", "")),
        resolved=resolved,
        dependency_hash=str(data.get("dependency_hash", "")),
    )
