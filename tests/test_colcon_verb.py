from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

from petal.colcon_ext.verb import DepsVerb


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    DepsVerb().add_arguments(parser=parser)
    return parser.parse_args(argv)


def test_colcon_deps_defaults_to_sync(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []
    monkeypatch.setattr("petal.colcon_ext.verb.cli.main", lambda argv: calls.append(argv) or 0)

    result = DepsVerb().main(context=SimpleNamespace(args=parse_args([])))

    assert result == 0
    assert calls == [["sync", "--workspace", str(Path.cwd())]]


def test_colcon_deps_sync_forwards_flags(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []
    monkeypatch.setattr("petal.colcon_ext.verb.cli.main", lambda argv: calls.append(argv) or 0)

    args = parse_args(["sync", "--workspace", str(tmp_path), "--dry-run", "--frozen"])
    result = DepsVerb().main(context=SimpleNamespace(args=args))

    assert result == 0
    assert calls == [["sync", "--workspace", str(tmp_path), "--dry-run", "--frozen"]]


def test_colcon_deps_status(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []
    monkeypatch.setattr("petal.colcon_ext.verb.cli.main", lambda argv: calls.append(argv) or 2)

    args = parse_args(["status", "--workspace", str(tmp_path)])
    result = DepsVerb().main(context=SimpleNamespace(args=args))

    assert result == 2
    assert calls == [["status", "--workspace", str(tmp_path)]]
