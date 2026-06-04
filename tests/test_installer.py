from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from petal.installer import InstallerError, execute, write_lock
from petal.models import Dep, ResolvedDep, Source
from petal.planner import Plan


def completed(cmd: list[str], stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")


def apt_dep(name: str = "numpy") -> ResolvedDep:
    return ResolvedDep(Dep(name), Source.APT, resolved_version="1.24", apt_pkg="python3-numpy")


def pip_dep(name: str = "rich") -> ResolvedDep:
    return ResolvedDep(Dep(name, ">=13"), Source.PIP, resolved_version="13.7.0")


def test_execute_dry_run_prints_commands(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    plan = Plan(apt=[apt_dep()], pip=[pip_dep()])
    execute(plan, tmp_path / "venv", dry_run=True)

    out = capsys.readouterr().out
    assert "sudo apt-get install -y python3-numpy" in out
    assert "uv pip install --python" in out
    assert "rich==13.7.0" in out


def test_execute_installs_missing_apt_and_pip_then_writes_lock(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    manifest = tmp_path / "petal.toml"
    manifest.write_text("[workspace]\nros_distro = \"humble\"\n", encoding="utf-8")
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if cmd[:2] == ["dpkg-query", "-W"]:
            return completed(cmd, returncode=1)
        return completed(cmd)

    execute(
        Plan(apt=[apt_dep()], pip=[pip_dep()]),
        tmp_path / "venv",
        workspace_root=tmp_path,
        manifest_path=manifest,
        runner=runner,
    )

    assert ["sudo", "apt-get", "install", "-y", "python3-numpy"] in calls
    assert ["uv", "pip", "install", "--python", str(tmp_path / "venv" / "bin" / "python"), "rich==13.7.0"] in calls
    lock = (tmp_path / "petal.lock").read_text(encoding="utf-8")
    assert "manifest_hash = \"sha256:" in lock
    assert 'name = "numpy"' in lock
    assert 'source = "apt"' in lock
    assert 'apt_pkg = "python3-numpy"' in lock
    assert 'name = "rich"' in lock
    assert 'version = "13.7.0"' in lock
    out = capsys.readouterr().out
    assert "APT: installing python3-numpy" in out
    assert "PIP: installing rich==13.7.0" in out
    assert "lock: wrote" in out


def test_execute_skips_installed_apt(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if cmd[:2] == ["dpkg-query", "-W"]:
            return completed(cmd, "install ok installed")
        return completed(cmd)

    execute(Plan(apt=[apt_dep()]), tmp_path / "venv", runner=runner)
    assert ["sudo", "apt-get", "install", "-y", "python3-numpy"] not in calls
    assert "APT: already installed python3-numpy" in capsys.readouterr().out


def test_execute_prints_noop_for_empty_plan(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    execute(Plan(), tmp_path / "venv")
    assert "petal: no dependencies to install" in capsys.readouterr().out


def test_execute_prints_distro_noop(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dep = ResolvedDep(Dep("rclpy"), Source.DISTRO, resolved_version="3.3.7")
    execute(Plan(distro=[dep]), tmp_path / "venv")
    assert "DISTRO: already provided rclpy" in capsys.readouterr().out


def test_write_lock_serializes_resolved_deps(tmp_path: Path) -> None:
    manifest = tmp_path / "petal.toml"
    manifest.write_text("[deps]\n", encoding="utf-8")
    lock = tmp_path / "petal.lock"

    write_lock(lock, manifest, [apt_dep(), pip_dep()])

    text = lock.read_text(encoding="utf-8")
    assert text.count("[[resolved]]") == 2
    assert 'source = "apt"' in text
    assert 'source = "pip"' in text


def test_frozen_errors_when_lock_missing(tmp_path: Path) -> None:
    with pytest.raises(InstallerError, match="petal.lock missing"):
        execute(Plan(pip=[pip_dep()]), tmp_path / "venv", frozen=True, workspace_root=tmp_path)


def test_frozen_errors_when_plan_differs_from_lock(tmp_path: Path) -> None:
    manifest = tmp_path / "petal.toml"
    manifest.write_text("[deps]\n", encoding="utf-8")
    write_lock(tmp_path / "petal.lock", manifest, [pip_dep("rich")])

    with pytest.raises(InstallerError, match="resolved deps differ"):
        execute(Plan(pip=[pip_dep("httpx")]), tmp_path / "venv", frozen=True, workspace_root=tmp_path)


def test_frozen_allows_matching_lock(tmp_path: Path) -> None:
    manifest = tmp_path / "petal.toml"
    manifest.write_text("[deps]\n", encoding="utf-8")
    write_lock(tmp_path / "petal.lock", manifest, [pip_dep("rich")])
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        return completed(cmd)

    execute(Plan(pip=[pip_dep("rich")]), tmp_path / "venv", frozen=True, workspace_root=tmp_path, runner=runner)
    assert calls == [["uv", "pip", "install", "--python", str(tmp_path / "venv" / "bin" / "python"), "rich==13.7.0"]]
