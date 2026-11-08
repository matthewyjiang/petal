from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from petal.config import load_lock, manifest_hash
from petal.identity import pip_name
from petal.models import Dep, Source
from petal.resolve.base import Runner, default_runner, venv_python
from petal.resolve.distro import DistroResolver
from petal.resolve.pip import venv_versions
from petal.system import SystemView


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
    workspace_root: Path,
    venv: Path,
    system: SystemView,
    runner: Runner = default_runner,
) -> StatusReport:
    """Compare petal.lock with what the venv and the ROS/system Python provide."""
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
                pip_versions = venv_versions(venv, runner)
            actual = pip_versions.get(pip_name(name), "")
            _bucket(report, name, actual, item.resolved_version)
        elif item.chosen_source == Source.DISTRO:
            # Same view of the system as resolution, independent of whether
            # this shell sourced ROS. The locked version is informational.
            if DistroResolver(system).resolve(Dep(name)):
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

    if report.manifest_changed or report.drifted:
        print("  run `petal sync` to update the lock and environment")
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


def _python_importable(name: str, venv: Path, runner: Runner) -> bool:
    module = DistroResolver._import_name(name)
    proc = runner([str(venv_python(venv)), "-c", f"import {module}"])
    return proc.returncode == 0
