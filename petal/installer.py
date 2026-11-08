from __future__ import annotations

import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from petal.config import load_lock_or_none
from petal.identity import lock_key, pip_name
from petal.models import LockStamp, ResolvedDep, Source
from petal.planner import Plan
from petal.resolve.base import (
    Runner,
    StreamRunner,
    default_runner,
    default_stream_runner,
    dep_requirement,
    venv_python,
)
from petal.resolve.pip import Pin, PipCompileError, compile_requirements, venv_versions
from petal.system import SystemView


class InstallerError(RuntimeError):
    pass


def execute(
    plan: Plan,
    venv: Path,
    *,
    system: SystemView,
    dry_run: bool = False,
    lock_path: Path | None = None,
    stamp: LockStamp | None = None,
    replan: Callable[[Plan], Plan] | None = None,
    verify: Callable[[], None] | None = None,
    runner: Runner = default_runner,
    install_runner: StreamRunner = default_stream_runner,
    assume_yes: bool = False,
    assume_no: bool = False,
) -> bool:
    """Install what `plan` needs, then record it in `lock_path` stamped `stamp`.

    Pip packages are installed as a fully resolved closure with `--no-deps`,
    skipping anything the ROS/system Python provides, so the venv never holds a
    copy that shadows a system package (unless the user explicitly allowed it).
    The closure is resolved before anything is installed. If apt changes what
    the system provides, `replan` revises the plan before pip runs. `verify`
    raises if the plan does not fit the system; it runs once the system is
    final, before the prompt when apt has nothing to install. Returns False
    when nothing was applied (dry run or cancelled).
    """
    for warning in plan.warnings:
        print(f"warning: {warning}")

    apt_pkgs = [item.apt_pkg for item in plan.apt if item.apt_pkg]
    installed = venv_versions(venv, runner) if plan.pip or plan.distro else {}
    pins = _pins_to_install(plan, venv, system, runner, installed)

    if dry_run:
        _print_plan(plan, venv)
        _print_dry_run(apt_pkgs, [pin.requirement for pin in pins], venv, system)
        return False

    _warn_shadowing(installed, system)
    missing_apt = [pkg for pkg in apt_pkgs if not _apt_installed(pkg, runner)]
    if verify and not missing_apt:
        verify()

    if not missing_apt and not pins:
        print(
            "petal: all dependencies already satisfied"
            if plan.items()
            else "petal: no dependencies to install"
        )
        if lock_path and stamp:
            _write_lock_if_changed(lock_path, stamp, plan.items())
        return True

    _print_changes(plan, missing_apt, pins)

    if not _confirm_install(assume_yes=assume_yes, assume_no=assume_no):
        print("petal: install cancelled")
        return False

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
        changed = system.refresh()
        if verify:
            verify()
        if changed:
            # New debs changed what the system provides, e.g. python3-scipy now
            # satisfies a `scipy` requirement that was headed for PyPI.
            if replan is not None:
                plan = replan(plan)
            pins = _pins_to_install(plan, venv, system, runner, installed)
    elif apt_pkgs:
        print("APT: already installed " + ", ".join(apt_pkgs))

    if pins:
        reqs = [pin.requirement for pin in pins]
        print("PIP: installing " + ", ".join(reqs))
        proc = install_runner(pip_install_command(venv, system, reqs))
        if proc.returncode != 0:
            raise InstallerError(proc.stderr or "pip install failed")

    if lock_path and stamp:
        _write_lock_if_changed(lock_path, stamp, plan.items())

    return True


def write_lock(lock_path: Path, stamp: LockStamp, resolved: list[ResolvedDep]) -> None:
    lines = [
        f'manifest_hash = "{stamp.manifest_hash}"',
        f'dependency_hash = "{stamp.dependency_hash}"',
        f'generated_at = "{datetime.now(timezone.utc).isoformat()}"',
        "",
    ]
    for item in resolved:
        lines.extend(_lock_entry(item))
    lock_path.write_text("\n".join(lines), encoding="utf-8")


def _write_lock_if_changed(
    lock_path: Path, stamp: LockStamp, resolved: list[ResolvedDep]
) -> None:
    if _lock_matches(lock_path, stamp, resolved):
        print("lock: unchanged")
        return
    write_lock(lock_path, stamp, resolved)
    print(f"lock: wrote {lock_path}")


def _lock_matches(
    lock_path: Path, stamp: LockStamp, resolved: list[ResolvedDep]
) -> bool:
    """True when writing `resolved` would not change petal.lock's content."""
    lock = load_lock_or_none(lock_path)
    if lock is None or lock.stamp != stamp:
        return False

    def entry(item: ResolvedDep) -> tuple[object, ...]:
        version = "" if item.chosen_source == Source.DISTRO else item.resolved_version
        dep = item.dep
        return (
            lock_key(item),
            item.chosen_source,
            item.apt_pkg,
            version,
            dep.version_spec,
            dep.source_hint,
        )

    return sorted(map(entry, lock.resolved), key=repr) == sorted(
        map(entry, resolved), key=repr
    )


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
    """One `[[resolved]]` table. System entries carry no version so the lock does
    not change with whichever machine resolved it."""
    lines = [
        "[[resolved]]",
        f'name = "{item.dep.name}"',
        f'source = "{item.chosen_source.value}"',
    ]
    if item.dep.version_spec:
        lines.append(f'spec = "{item.dep.version_spec}"')
    if item.dep.source_hint:
        lines.append(f'hint = "{item.dep.source_hint.value}"')
    if item.apt_pkg:
        lines.append(f'apt_pkg = "{item.apt_pkg}"')
    if item.resolved_version and item.chosen_source != Source.DISTRO:
        lines.append(f'version = "{item.resolved_version}"')
    lines.append("")
    return lines


def _pip_requirement(item: ResolvedDep) -> str:
    if item.resolved_version and not item.dep.name.startswith("git+"):
        return f"{item.dep.name}=={item.resolved_version}"
    return dep_requirement(item.dep)


def pip_install_command(venv: Path, system: SystemView, reqs: list[str]) -> list[str]:
    """`uv pip install` for an already-resolved closure, guarded by system pins."""
    python = str(venv_python(venv))
    return [
        *("uv", "pip", "install", "--python", python, "--no-deps"),
        *system.constraint_args(),
        *reqs,
    ]


def _pins_to_install(
    plan: Plan,
    venv: Path,
    system: SystemView,
    runner: Runner,
    installed: dict[str, str],
) -> list[Pin]:
    """Pins pip must install: the resolved closure minus system and venv copies.

    Empty when every top-level pip dep is already installed at its version.
    """
    if not _missing_pip(plan.pip, installed):
        return []
    reqs = [_pip_requirement(item) for item in plan.pip]
    try:
        pins = compile_requirements(reqs, venv, system, runner, installed)
    except PipCompileError as exc:
        raise InstallerError(f"pip dependencies cannot be resolved:\n{exc}") from exc
    return [
        pin
        for pin in pins
        if not system.protects(pin.name)
        and not (pin.version and installed.get(pin.name) == pin.version)
    ]


def _warn_shadowing(installed: dict[str, str], system: SystemView) -> None:
    """Flag venv copies of system packages, e.g. left by older petal versions."""
    for name, version in sorted(system.shadowed_by(installed).items()):
        print(
            f"warning: .petal/venv has {name} {version}, shadowing the system's "
            f"{system.version(name)}; run `petal clean && petal sync` to drop it"
        )


def _missing_pip(
    items: list[ResolvedDep], installed: dict[str, str]
) -> list[ResolvedDep]:
    missing: list[ResolvedDep] = []
    for item in items:
        key = pip_name(item.dep.name)
        actual = installed.get(key)
        if not actual or (item.resolved_version and actual != item.resolved_version):
            missing.append(item)
    return missing


def _print_plan(plan: Plan, venv: Path) -> None:
    items = plan.items()
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


def _print_changes(plan: Plan, missing_apt: list[str], pins: list[Pin]) -> None:
    change_count = len(missing_apt) + len(pins)
    noun = "change" if change_count == 1 else "changes"
    pin_names = {pin.name for pin in pins}
    satisfied = (
        len(plan.distro)
        + (len(plan.apt) - len(missing_apt))
        + sum(1 for item in plan.pip if pip_name(item.dep.name) not in pin_names)
    )
    print(f"{change_count} {noun} to apply  ·  {satisfied} already satisfied")
    if missing_apt:
        print("  apt:")
        missing_apt_set = set(missing_apt)
        for item in plan.apt:
            if item.apt_pkg in missing_apt_set:
                version = f" {item.resolved_version}" if item.resolved_version else ""
                print(
                    f"    {item.dep.name} -> {item.apt_pkg or item.dep.name}{version}"
                )
    if pins:
        print("  pip:")
        for pin in pins:
            print(f"    {pin.requirement}")


def _confirm_install(*, assume_yes: bool, assume_no: bool) -> bool:
    if assume_yes:
        return True
    if assume_no:
        return False
    if not sys.stdin.isatty():
        raise InstallerError("install requires confirmation; rerun with --yes")
    answer = input("Proceed with install? [Y/n] ").strip().lower()
    return answer in {"", "y", "yes"}


def _print_dry_run(
    apt_pkgs: list[str], pip_reqs: list[str], venv: Path, system: SystemView
) -> None:
    if apt_pkgs:
        print("APT:")
        print("sudo apt-get install -y " + " ".join(apt_pkgs))
    else:
        print("APT: no changes")

    if pip_reqs:
        print("PIP:")
        print(" ".join(pip_install_command(venv, system, pip_reqs)))
    else:
        print("PIP: no changes")


def _apt_installed(pkg: str, runner: Runner) -> bool:
    proc = runner(["dpkg-query", "-W", "-f=${Status}", pkg])
    return proc.returncode == 0 and "install ok installed" in proc.stdout
