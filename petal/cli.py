from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from petal import env
from petal.config import find_workspace_root, load_manifest, write_manifest
from petal.discover.workspace import discover_workspace
from petal.installer import InstallerError, execute
from petal.planner import PlannerConflict, build_plan
from petal.resolve.manager import ResolutionManager
from petal.status import check_status, print_report


def _cmd_init(args: argparse.Namespace) -> int:
    workspace = find_workspace_root(Path(args.workspace) if args.workspace else Path.cwd())
    distro = env.detect_ros_distro()
    interpreter = env.distro_python(distro)
    py_version = env.python_version(interpreter)
    manifest = workspace / "petal.toml"
    if not manifest.exists():
        write_manifest(manifest, ros_distro=distro, python_version=py_version)
    venv = env.ensure_venv(workspace, distro)
    print(f"initialized {workspace}")
    print(f"venv: {venv}")
    print(f"activate: {workspace / '.petal' / 'activate'}")
    return 0


def _cmd_activate(args: argparse.Namespace) -> int:
    workspace = find_workspace_root(Path(args.workspace) if args.workspace else Path.cwd())
    print(workspace / ".petal" / "activate")
    return 0


def _cmd_clean(args: argparse.Namespace) -> int:
    workspace = find_workspace_root(Path(args.workspace) if args.workspace else Path.cwd())
    shutil.rmtree(workspace / ".petal" / "venv", ignore_errors=True)
    return 0


def _cmd_sync(args: argparse.Namespace) -> int:
    workspace = find_workspace_root(Path(args.workspace) if args.workspace else Path.cwd())
    manifest_path = workspace / "petal.toml"
    manifest = load_manifest(manifest_path) if manifest_path.exists() else None
    distro = manifest.ros_distro if manifest and manifest.ros_distro else env.detect_ros_distro()
    venv = env.ensure_venv(workspace, distro)

    discovered = discover_workspace(workspace)
    deps = [*(manifest.deps if manifest else []), *discovered.deps]
    manager = ResolutionManager(ros_distro=distro, venv=venv)
    resolved = [item for dep in deps if (item := manager.resolve(dep))]
    plan = build_plan(resolved)
    execute(
        plan,
        venv,
        frozen=args.frozen,
        dry_run=args.dry_run,
        workspace_root=workspace,
        manifest_path=manifest_path,
    )
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    workspace = find_workspace_root(Path(args.workspace) if args.workspace else Path.cwd())
    manifest_path = workspace / "petal.toml"
    manifest = load_manifest(manifest_path) if manifest_path.exists() else None
    distro = manifest.ros_distro if manifest and manifest.ros_distro else env.detect_ros_distro()
    venv = env.venv_path(workspace)
    if not venv.exists():
        venv = env.ensure_venv(workspace, distro)
    report = check_status(workspace, venv)
    print_report(report)
    return 0 if report.ok else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="petal")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="detect ROS distro and create workspace venv")
    init.add_argument("--workspace")
    init.set_defaults(func=_cmd_init)

    activate = sub.add_parser("activate", help="print activation helper path")
    activate.add_argument("--workspace")
    activate.set_defaults(func=_cmd_activate)

    clean = sub.add_parser("clean", help="remove petal venv")
    clean.add_argument("--workspace")
    clean.set_defaults(func=_cmd_clean)

    sync = sub.add_parser("sync", help="resolve and install workspace dependencies")
    sync.add_argument("--workspace")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--frozen", action="store_true")
    sync.set_defaults(func=_cmd_sync)

    status = sub.add_parser("status", help="report manifest/lock/install drift")
    status.add_argument("--workspace")
    status.set_defaults(func=_cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (env.PetalEnvError, PlannerConflict, InstallerError) as exc:
        print(f"petal: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
