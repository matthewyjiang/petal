from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from petal.config import load_lock, manifest_hash
from petal.models import ResolvedDep, Source
from petal.planner import Plan
from petal.resolve.base import (
    Runner,
    StreamRunner,
    default_runner,
    default_stream_runner,
    dep_requirement,
    venv_python,
)


class InstallerError(RuntimeError):
    pass


def execute(
    plan: Plan,
    venv: Path,
    *,
    frozen: bool = False,
    dry_run: bool = False,
    workspace_root: Path | None = None,
    manifest_path: Path | None = None,
    runner: Runner = default_runner,
    install_runner: StreamRunner = default_stream_runner,
    assume_yes: bool = False,
    assume_no: bool = False,
) -> None:
    if frozen:
        if not workspace_root:
            raise InstallerError("frozen install requires workspace root")
        lock_path = workspace_root / "petal.lock"
        if not lock_path.exists():
            raise InstallerError("petal.lock missing; run `petal sync` first")
        _check_frozen(lock_path, [*plan.distro, *plan.apt, *plan.pip])

    for warning in plan.warnings:
        print(f"warning: {warning}")

    apt_pkgs = [item.apt_pkg for item in plan.apt if item.apt_pkg]
    pip_reqs = [_pip_requirement(item) for item in plan.pip]
    distro_names = [item.dep.name for item in plan.distro]

    _print_plan(plan, venv)

    if dry_run:
        _print_dry_run(apt_pkgs, pip_reqs, venv)
        return

    if distro_names:
        print("DISTRO: already provided " + ", ".join(distro_names))

    missing_apt = [pkg for pkg in apt_pkgs if not _apt_installed(pkg, runner)]
    will_install = bool(missing_apt or pip_reqs)
    if will_install and not _confirm_install(assume_yes=assume_yes, assume_no=assume_no):
        print("petal: install cancelled")
        return

    if missing_apt:
        print("APT: installing " + ", ".join(missing_apt))
        try:
            proc = install_runner(["sudo", "apt-get", "install", "-y", *missing_apt])
        except KeyboardInterrupt:
            print(
                "petal: apt interrupted; you may need: sudo dpkg --configure -a",
                file=sys.stderr,
            )
            raise
        if proc.returncode != 0:
            raise InstallerError(proc.stderr or "apt install failed")
    elif apt_pkgs:
        print("APT: already installed " + ", ".join(apt_pkgs))

    if pip_reqs:
        print("PIP: installing " + ", ".join(pip_reqs))
        proc = install_runner(["uv", "pip", "install", "--python", str(venv_python(venv)), *pip_reqs])
        if proc.returncode != 0:
            pip_proc = install_runner([str(venv_python(venv)), "-m", "pip", "install", *pip_reqs])
            if pip_proc.returncode != 0:
                raise InstallerError(pip_proc.stderr or proc.stderr or "pip install failed")

    if not distro_names and not apt_pkgs and not pip_reqs:
        print("petal: no dependencies to install")

    if workspace_root and manifest_path:
        write_lock(workspace_root / "petal.lock", manifest_path, [*plan.distro, *plan.apt, *plan.pip])
        print(f"lock: wrote {workspace_root / 'petal.lock'}")


def write_lock(lock_path: Path, manifest_path: Path, resolved: list[ResolvedDep]) -> None:
    lines = [
        f'manifest_hash = "{manifest_hash(manifest_path)}"',
        f'generated_at = "{datetime.now(timezone.utc).isoformat()}"',
        "",
    ]
    for item in resolved:
        lines.extend(_lock_entry(item))
    lock_path.write_text("\n".join(lines), encoding="utf-8")


def uninstall(
    name: str,
    venv: Path,
    *,
    dry_run: bool = False,
    runner: Runner = default_runner,
) -> None:
    uv_cmd = ["uv", "pip", "uninstall", "--python", str(venv_python(venv)), name]
    if dry_run:
        print("PIP uninstall:")
        print(" ".join(uv_cmd))
        return

    proc = runner(uv_cmd)
    if proc.returncode == 0:
        return

    pip_proc = runner([str(venv_python(venv)), "-m", "pip", "uninstall", "-y", name])
    if pip_proc.returncode != 0:
        raise InstallerError(pip_proc.stderr or proc.stderr or "pip uninstall failed")


def _lock_entry(item: ResolvedDep) -> list[str]:
    lines = ["[[resolved]]", f'name = "{item.dep.name}"', f'source = "{item.chosen_source.value}"']
    if item.apt_pkg:
        lines.append(f'apt_pkg = "{item.apt_pkg}"')
    if item.resolved_version:
        lines.append(f'version = "{item.resolved_version}"')
    lines.append("")
    return lines


def _pip_requirement(item: ResolvedDep) -> str:
    if item.resolved_version and not item.dep.name.startswith("git+"):
        return f"{item.dep.name}=={item.resolved_version}"
    return dep_requirement(item.dep)


def _print_plan(plan: Plan, venv: Path) -> None:
    items = [*plan.distro, *plan.apt, *plan.pip]
    if not items:
        return
    print(f"Resolved {len(items)} dependencies:")
    for item in plan.distro:
        version = f" {item.resolved_version}" if item.resolved_version else ""
        print(f"  {item.dep.name:<24} distro   provided by ROS/system{version}")
    for item in plan.apt:
        source = "rosdep/apt" if item.dep.source_hint == Source.ROSDEP else "apt"
        target = item.apt_pkg or item.dep.name
        version = f" {item.resolved_version}" if item.resolved_version else ""
        print(f"  {item.dep.name:<24} {source:<9} {target}{version}")
    for item in plan.pip:
        print(
            f"  {item.dep.name:<24} pip      "
            f"{_pip_requirement(item)} -> {venv_python(venv)}"
        )


def _confirm_install(*, assume_yes: bool, assume_no: bool) -> bool:
    if assume_yes:
        return True
    if assume_no:
        return False
    if not sys.stdin.isatty():
        raise InstallerError("install requires confirmation; rerun with --yes")
    answer = input("Proceed with install? [Y/n] ").strip().lower()
    return answer in {"", "y", "yes"}


def _print_dry_run(apt_pkgs: list[str], pip_reqs: list[str], venv: Path) -> None:
    if apt_pkgs:
        print("APT:")
        print("sudo apt-get install -y " + " ".join(apt_pkgs))
    else:
        print("APT: no changes")

    if pip_reqs:
        print("PIP:")
        print("uv pip install --python " + str(venv_python(venv)) + " " + " ".join(pip_reqs))
    else:
        print("PIP: no changes")


def _apt_installed(pkg: str, runner: Runner) -> bool:
    proc = runner(["dpkg-query", "-W", "-f=${Status}", pkg])
    return proc.returncode == 0 and "install ok installed" in proc.stdout


def _check_frozen(lock_path: Path, planned: list[ResolvedDep]) -> None:
    locked = load_lock(lock_path).resolved
    locked_map = {_frozen_key(item): item for item in locked}
    planned_map = {_frozen_key(item): item for item in planned}
    if locked_map.keys() != planned_map.keys():
        raise InstallerError("resolved deps differ from petal.lock; run `petal sync`")
    for key, planned_item in planned_map.items():
        locked_item = locked_map[key]
        if planned_item.chosen_source != locked_item.chosen_source:
            raise InstallerError(f"{key} source differs from petal.lock")
        if planned_item.apt_pkg != locked_item.apt_pkg:
            raise InstallerError(f"{key} apt package differs from petal.lock")
        if locked_item.resolved_version and planned_item.resolved_version != locked_item.resolved_version:
            raise InstallerError(f"{key} version differs from petal.lock")


def _frozen_key(item: ResolvedDep) -> str:
    return item.dep.name.lower().replace("_", "-")
