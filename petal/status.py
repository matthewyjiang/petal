from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from petal.config import load_lock, manifest_hash
from petal.identity import pip_name
from petal.models import Source
from petal.resolve.base import Runner, default_runner, venv_python
from petal.resolve.distro import DistroResolver


@dataclass
class StatusReport:
    in_sync: list[str] = field(default_factory=list)
    drifted: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    manifest_changed: bool = False

    @property
    def ok(self) -> bool:
        return not self.drifted and not self.missing and not self.manifest_changed


def check_status(
    workspace_root: Path, venv: Path, runner: Runner = default_runner
) -> StatusReport:
    lock_path = workspace_root / "petal.lock"
    manifest_path = workspace_root / "petal.toml"
    report = StatusReport()
    if not lock_path.exists():
        report.missing.append("petal.lock")
        return report

    lock = load_lock(lock_path)
    if manifest_path.exists() and lock.manifest_hash != manifest_hash(manifest_path):
        report.manifest_changed = True

    pip_versions: dict[str, str] | None = None
    for item in lock.resolved:
        name = item.dep.name
        if item.chosen_source == Source.APT:
            actual = _apt_version(item.apt_pkg, runner)
            if actual:
                _bucket(report, name, actual, item.resolved_version)
            elif _python_importable(name, venv, runner):
                report.in_sync.append(name)
            else:
                report.missing.append(name)
        elif item.chosen_source == Source.PIP:
            if pip_versions is None:
                pip_versions = _pip_versions(venv, runner)
            actual = pip_versions.get(pip_name(name), "")
            _bucket(report, name, actual, item.resolved_version)
        elif item.chosen_source == Source.DISTRO:
            if _distro_importable(name, venv, runner):
                report.in_sync.append(name)
            else:
                report.missing.append(name)
    return report


def print_report(report: StatusReport) -> None:
    parts = [f"{len(report.in_sync)} synced"]
    if report.drifted:
        parts.append(f"{len(report.drifted)} drifted")
    if report.missing:
        parts.append(f"{len(report.missing)} missing")
    if report.manifest_changed:
        parts.append("manifest changed")
    print("  ·  ".join(parts))

    if report.ok:
        return

    if report.manifest_changed:
        print("  run `petal sync` to update the lock")
    if report.drifted:
        print("  drifted:")
        for item in report.drifted:
            print(f"    {item}")
    if report.missing:
        print("  missing:")
        for item in report.missing:
            print(f"    {item}")


def _bucket(report: StatusReport, name: str, actual: str, expected: str) -> None:
    if not actual:
        report.missing.append(name)
    elif expected and actual != expected:
        report.drifted.append(f"{name} ({actual} != {expected})")
    else:
        report.in_sync.append(name)


def _apt_version(pkg: str, runner: Runner) -> str:
    proc = runner(["dpkg-query", "-W", "-f=${Version}", pkg])
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _pip_versions(venv: Path, runner: Runner) -> dict[str, str]:
    proc = runner(
        ["uv", "pip", "list", "--python", str(venv_python(venv)), "--format", "json"]
    )
    if proc.returncode != 0:
        proc = runner([str(venv_python(venv)), "-m", "pip", "list", "--format", "json"])
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return {}
    return {pip_name(str(item["name"])): str(item["version"]) for item in data}


def _distro_importable(name: str, venv: Path, runner: Runner) -> bool:
    return _python_importable(name, venv, runner)


def _python_importable(name: str, venv: Path, runner: Runner) -> bool:
    module = DistroResolver._import_name(name)
    proc = runner([str(venv_python(venv)), "-c", f"import {module}"])
    return proc.returncode == 0
