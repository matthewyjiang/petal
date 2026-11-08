from __future__ import annotations

import argparse
import shlex
import shutil
import sys
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from petal import env, preflight
from petal.config import (
    add_manifest_dep,
    find_workspace_root,
    load_lock_or_none,
    load_manifest,
    lock_stamp,
    manifest_has_dep,
    remove_manifest_dep,
    write_manifest,
)
from petal.discover.workspace import discover_workspace
from petal.host import Host
from petal.identity import pip_name
from petal.installer import InstallerError, execute, uninstall, write_lock
from petal.models import Dep, Lock, LockStamp, ResolvedDep, Source
from petal.planner import Plan, PlannerConflict, build_plan
from petal.resolve.manager import (
    ResolutionManager,
    UnresolvedDependencies,
    lock_mismatch,
)
from petal.status import check_status, print_report
from petal.system import SystemView


def _cmd_init(args: argparse.Namespace, host: Host) -> int:
    workspace = find_workspace_root(
        Path(args.workspace) if args.workspace else Path.cwd()
    )
    distro = host.detect_ros_distro()
    manifest = workspace / "petal.toml"
    if not manifest.exists():
        write_manifest(manifest, ros_distro=distro)
    venv = host.ensure_venv(workspace, distro)
    print(f"initialized {workspace}")
    print(f"venv: {venv}")
    print(f"activate: {workspace / '.petal' / 'activate'}")
    return 0


def _cmd_activate(args: argparse.Namespace, host: Host) -> int:
    workspace = find_workspace_root(
        Path(args.workspace) if args.workspace else Path.cwd()
    )
    script = workspace / ".petal" / "activate"
    if not script.is_file():
        # `source <(petal activate)` ignores our exit code and stderr, so
        # print a line that fails where it is sourced.
        message = f"petal: {script} not found; run `petal init` first"
        print(f"echo {shlex.quote(message)} >&2; return 1")
        return 1
    # Print a line that sources the script so `source <(petal activate)` and
    # `. .petal/activate` behave identically.
    shell = f"PETAL_SHELL={args.shell} " if args.shell else ""
    print(f"{shell}. {shlex.quote(str(script))}")
    return 0


def _cmd_clean(args: argparse.Namespace, host: Host) -> int:
    workspace = find_workspace_root(
        Path(args.workspace) if args.workspace else Path.cwd()
    )
    shutil.rmtree(workspace / ".petal" / "venv", ignore_errors=True)
    return 0


@dataclass(frozen=True)
class _Inputs:
    """Everything a resolution depends on, and the lock stamp that identifies it."""

    deps: list[Dep]
    system: SystemView
    stamp: LockStamp


def _load_inputs(
    host: Host, workspace: Path, manifest_path: Path, distro: str
) -> _Inputs:
    manifest = load_manifest(manifest_path) if manifest_path.exists() else None
    manifest_deps = manifest.deps if manifest else []
    deps = [*manifest_deps, *discover_workspace(workspace, ros_distro=distro).deps]
    system = SystemView(
        lambda: host.inspect_system(distro),
        constraints_path=workspace / ".petal" / "constraints.txt",
        # Explicit `{ pip = ... }` entries in [deps] may shadow system copies.
        allow_shadow=[d.name for d in manifest_deps if d.source_hint == Source.PIP],
    )
    return _Inputs(deps, system, lock_stamp(manifest_path, deps))


def _manager(
    host: Host, inputs: _Inputs, distro: str, venv: Path, lock: Lock | None
) -> ResolutionManager:
    """Resolver for the workspace that keeps locked PyPI versions when it can."""
    locked = {
        pip_name(item.dep.name): item.resolved_version
        for item in (lock.resolved if lock else [])
        if item.chosen_source == Source.PIP
    }
    return ResolutionManager(
        ros_distro=distro,
        venv=venv,
        system=inputs.system,
        locked=locked,
        runner=host.runner,
    )


def _workspace_plan(
    host: Host, inputs: _Inputs, distro: str, venv: Path, lock: Lock | None
) -> Plan:
    """Resolve the whole workspace; raises before anything is installed."""
    manager = _manager(host, inputs, distro, venv, lock)
    return build_plan(manager.resolve_all(inputs.deps))


def _sync(
    host: Host,
    workspace: Path,
    distro: str,
    venv: Path,
    *,
    reuse_lock: bool,
    frozen: bool = False,
    dry_run: bool = False,
    assume_yes: bool = False,
    assume_no: bool = False,
) -> bool:
    """Bring the venv and petal.lock in line with petal.toml and the workspace.

    `frozen` installs what petal.lock records and never rewrites it. Otherwise
    the lock is reused only while its inputs are unchanged and it still fits
    this system; anything else resolves the workspace again.
    """
    manifest_path = workspace / "petal.toml"
    lock_path = workspace / "petal.lock"
    inputs = _load_inputs(host, workspace, manifest_path, distro)
    lock = load_lock_or_none(lock_path)

    def replan(plan: Plan) -> Plan:
        manager = _manager(host, inputs, distro, venv, lock)
        return build_plan(manager.reselect_python(plan.items()))

    if frozen:
        if lock is None:
            raise InstallerError("petal.lock missing; run `petal sync` first")
        if lock.stamp != inputs.stamp:
            raise InstallerError(
                "petal.lock is out of date with petal.toml or the workspace; "
                "run `petal sync`"
            )
        frozen_lock = lock

        def verify(*, check_distro: bool = True) -> None:
            # System packages the lock relies on may arrive with its own apt
            # entries, so execute() checks them once apt is done.
            reason = lock_mismatch(
                frozen_lock.resolved, inputs.system, check_distro=check_distro
            )
            if reason:
                raise InstallerError(f"petal.lock does not fit this system: {reason}")

        verify(check_distro=False)
        return execute(
            build_plan(lock.resolved),
            venv,
            system=inputs.system,
            dry_run=dry_run,
            assume_yes=True,
            verify=verify,
            runner=host.runner,
            install_runner=host.install_runner,
        )

    fits = lock is not None and not lock_mismatch(lock.resolved, inputs.system)
    if reuse_lock and lock and lock.stamp == inputs.stamp and fits:
        plan = build_plan(lock.resolved)
    else:
        plan = _workspace_plan(host, inputs, distro, venv, lock)
    return execute(
        plan,
        venv,
        system=inputs.system,
        dry_run=dry_run,
        assume_yes=assume_yes,
        assume_no=assume_no,
        lock_path=lock_path,
        stamp=inputs.stamp,
        replan=replan,
        runner=host.runner,
        install_runner=host.install_runner,
    )


def _cmd_sync(args: argparse.Namespace, host: Host) -> int:
    preflight.assert_ok(host.check_tools())
    workspace = find_workspace_root(
        Path(args.workspace) if args.workspace else Path.cwd()
    )
    manifest_path = workspace / "petal.toml"
    manifest = load_manifest(manifest_path) if manifest_path.exists() else None
    distro = (
        manifest.ros_distro
        if manifest and manifest.ros_distro
        else host.detect_ros_distro()
    )
    venv = host.ensure_venv(workspace, distro)
    _sync(
        host,
        workspace,
        distro,
        venv,
        reuse_lock=not args.dry_run,
        frozen=args.frozen,
        dry_run=args.dry_run,
        assume_yes=args.yes,
        assume_no=args.no,
    )
    return 0


def _cmd_add(args: argparse.Namespace, host: Host) -> int:
    preflight.assert_ok(host.check_tools())
    workspace = find_workspace_root(
        Path(args.workspace) if args.workspace else Path.cwd()
    )
    manifest_path = workspace / "petal.toml"
    if not manifest_path.exists():
        write_manifest(manifest_path, ros_distro=host.detect_ros_distro())

    manifest = load_manifest(manifest_path)
    distro = manifest.ros_distro or host.detect_ros_distro()
    venv = host.ensure_venv(workspace, distro)
    source_hint = Source.PIP if args.pip else Source.APT if args.apt else None

    original = manifest_path.read_bytes()
    add_manifest_dep(
        manifest_path,
        args.name,
        version_spec=args.spec or "",
        source_hint=source_hint,
        apt_pkg=args.spec or "" if args.apt else "",
    )
    try:
        # `add` is a sync of the edited manifest; any failure restores it.
        proceeded = _sync(
            host,
            workspace,
            distro,
            venv,
            reuse_lock=False,
            dry_run=args.dry_run,
            assume_yes=args.yes,
            assume_no=args.no,
        )
    except BaseException:
        manifest_path.write_bytes(original)
        raise
    if not proceeded:
        manifest_path.write_bytes(original)
    return 0


def _cmd_remove(args: argparse.Namespace, host: Host) -> int:
    preflight.assert_ok(host.check_tools())
    workspace = find_workspace_root(
        Path(args.workspace) if args.workspace else Path.cwd()
    )
    manifest_path = workspace / "petal.toml"
    if not manifest_path.exists():
        print("petal.toml missing; nothing to remove")
        return 0

    manifest = load_manifest(manifest_path)
    distro = manifest.ros_distro or host.detect_ros_distro()
    venv = host.ensure_venv(workspace, distro)
    if not manifest_has_dep(manifest_path, args.name):
        print(f"{args.name} not present in petal.toml")
        return 0

    lock_path = workspace / "petal.lock"
    lock = load_lock_or_none(lock_path)
    original = manifest_path.read_bytes()
    remove_manifest_dep(manifest_path, args.name)
    try:
        # Same ordering as add: validate the post-change workspace first.
        inputs = _load_inputs(host, workspace, manifest_path, distro)
        plan = _workspace_plan(host, inputs, distro, venv, lock)
        # Uninstall what nothing pins anymore: the dep and what only it pulled in.
        before = _pip_names(lock.resolved) if lock else {pip_name(args.name)}
        stale = sorted(before - _pip_names(plan.items()))
        uninstall(stale, venv, dry_run=args.dry_run, runner=host.runner)
    except BaseException:
        manifest_path.write_bytes(original)
        raise
    if args.dry_run:
        manifest_path.write_bytes(original)
        return 0
    write_lock(lock_path, inputs.stamp, plan.items())
    return 0


def _pip_names(items: list[ResolvedDep]) -> set[str]:
    return {pip_name(i.dep.name) for i in items if i.chosen_source == Source.PIP}


def _cmd_status(args: argparse.Namespace, host: Host) -> int:
    preflight.assert_ok(host.check_tools())
    workspace = find_workspace_root(
        Path(args.workspace) if args.workspace else Path.cwd()
    )
    manifest_path = workspace / "petal.toml"
    manifest = load_manifest(manifest_path) if manifest_path.exists() else None
    distro = (
        manifest.ros_distro
        if manifest and manifest.ros_distro
        else host.detect_ros_distro()
    )
    venv = env.venv_path(workspace)
    if not venv.exists():
        venv = host.ensure_venv(workspace, distro)
    report = check_status(
        workspace,
        venv,
        lambda: SystemView(lambda: host.inspect_system(distro), constraints_path=None),
        host.runner,
    )
    print_report(report)
    return 0 if report.ok else 2


def _skill_source() -> Path:
    candidates: list[Path] = []
    try:
        dist = metadata.distribution("petal-ros")
        candidates.append(Path(str(dist.locate_file("skills/petal-cli"))))
    except metadata.PackageNotFoundError:
        pass
    candidates.append(Path(__file__).resolve().parent.parent / "skills" / "petal-cli")

    for candidate in candidates:
        if (candidate / "SKILL.md").is_file():
            return candidate
    raise FileNotFoundError(
        "could not locate the petal-cli agent skill; reinstall petal-ros"
    )


def _cmd_install_agent_skill(args: argparse.Namespace, host: Host) -> int:
    target_root = (
        Path(args.target).expanduser()
        if args.target
        else Path.home() / ".agents" / "skills"
    )
    target = target_root / "petal-cli"
    target_exists = target.exists() or target.is_symlink()

    if target_exists and not args.force:
        print(f"agent skill already installed: {target}")
        print("use --force to replace it")
        return 0

    try:
        source = _skill_source()
        if target_exists:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            else:
                target.unlink()
        target_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, target)
    except OSError as exc:
        print(f"petal: failed to install agent skill: {exc}", file=sys.stderr)
        return 1

    print(f"installed petal-cli agent skill to {target}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="petal")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="detect ROS distro and create workspace venv")
    init.add_argument("--workspace")
    init.set_defaults(func=_cmd_init)

    activate = sub.add_parser(
        "activate",
        help="print a line that activates ROS + the petal venv (source <(petal activate))",
    )
    activate.add_argument("--workspace")
    activate.add_argument(
        "--shell",
        choices=["bash", "zsh", "sh"],
        default=None,
        help="ROS 2-supported shell dialect (default: auto-detect from $SHELL)",
    )
    activate.set_defaults(func=_cmd_activate)

    clean = sub.add_parser("clean", help="remove petal venv")
    clean.add_argument("--workspace")
    clean.set_defaults(func=_cmd_clean)

    sync = sub.add_parser("sync", help="resolve and install workspace dependencies")
    sync.add_argument("--workspace")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--frozen", action="store_true")
    sync_prompt = sync.add_mutually_exclusive_group()
    sync_prompt.add_argument(
        "-y", "--yes", action="store_true", help="install without prompting"
    )
    sync_prompt.add_argument(
        "--no", action="store_true", help="print plan and do not install"
    )
    sync.set_defaults(func=_cmd_sync)

    add = sub.add_parser("add", help="add a dependency to petal.toml and sync it")
    add.add_argument("name")
    add.add_argument("spec", nargs="?", default="")
    add.add_argument("--workspace")
    add.add_argument("--dry-run", action="store_true")
    add_prompt = add.add_mutually_exclusive_group()
    add_prompt.add_argument(
        "-y", "--yes", action="store_true", help="install without prompting"
    )
    add_prompt.add_argument(
        "--no", action="store_true", help="print plan and do not install"
    )
    source = add.add_mutually_exclusive_group()
    source.add_argument("--pip", action="store_true")
    source.add_argument("--apt", action="store_true")
    add.set_defaults(func=_cmd_add)

    remove = sub.add_parser("remove", help="remove a dependency from petal.toml")
    remove.add_argument("name")
    remove.add_argument("--workspace")
    remove.add_argument("--dry-run", action="store_true")
    remove.set_defaults(func=_cmd_remove)

    status = sub.add_parser("status", help="report manifest/lock/install drift")
    status.add_argument("--workspace")
    status.set_defaults(func=_cmd_status)

    skill = sub.add_parser(
        "install-agent-skill", help="install the Petal CLI agent skill"
    )
    skill.add_argument("--target", help="skills directory (default: ~/.agents/skills)")
    skill.add_argument(
        "--force", action="store_true", help="replace an existing petal-cli skill"
    )
    skill.set_defaults(func=_cmd_install_agent_skill)
    return parser


def main(argv: list[str] | None = None, host: Host | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args, host or Host())
    except KeyboardInterrupt:
        print("petal: cancelled", file=sys.stderr)
        return 130
    except (
        env.PetalEnvError,
        PlannerConflict,
        InstallerError,
        UnresolvedDependencies,
    ) as exc:
        print(f"petal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
