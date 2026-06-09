from __future__ import annotations

from pathlib import Path

from petal import cli

try:  # pragma: no cover - real colcon not required in unit tests
    from colcon_core.verb import VerbExtensionPoint
except ModuleNotFoundError:  # pragma: no cover

    class VerbExtensionPoint:  # type: ignore[no-redef]
        """Small fallback so tests/imports work without colcon installed."""


class DepsVerb(VerbExtensionPoint):
    """`colcon deps sync` wrapper around `petal sync`."""

    def add_arguments(self, *, parser) -> None:  # type: ignore[no-untyped-def]
        parser.add_argument(
            "action",
            nargs="?",
            default="sync",
            choices=["sync", "status"],
            help="dependency action to run",
        )
        parser.add_argument("--workspace", default=None)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--frozen", action="store_true")

    def main(self, *, context) -> int:  # type: ignore[no-untyped-def]
        args = context.args
        workspace = args.workspace or str(Path.cwd())
        command = [args.action, "--workspace", workspace]
        if args.action == "sync":
            if args.dry_run:
                command.append("--dry-run")
            if args.frozen:
                command.append("--frozen")
        return cli.main(command)
