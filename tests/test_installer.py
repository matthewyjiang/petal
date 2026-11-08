from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from petal.config import lock_stamp
from petal.installer import InstallerError, write_lock
from petal.installer import execute as _execute
from petal.models import Dep, ResolvedDep, Source
from petal.planner import Plan
from petal.system import NO_SYSTEM, SystemPython, SystemView


def completed(
    cmd: list[str], stdout: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")


def execute(*args, **kwargs):  # type: ignore[no-untyped-def]
    kwargs.setdefault("system", NO_SYSTEM)
    return _execute(*args, **kwargs)


def fake_uv(cmd, **kwargs):  # type: ignore[no-untyped-def]
    """Empty venv for `uv pip list`, `compiled` for `uv pip compile`."""
    if cmd[:3] == ["uv", "pip", "list"]:
        return completed(cmd, "[]")
    return compiled(cmd, kwargs)


def compiled(cmd: list[str], kwargs: dict) -> subprocess.CompletedProcess[str]:
    """Fake `uv pip compile`: pins each stdin requirement plus pygments for rich."""
    lines = kwargs["input"].split()
    if any(line.startswith("rich") for line in lines):
        lines.append("pygments==2.18.0")
    output = Path(cmd[cmd.index("--output-file") + 1])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return completed(cmd)


def install_cmd(tmp_path: Path, *reqs: str) -> list[str]:
    python = str(tmp_path / "venv" / "bin" / "python")
    return ["uv", "pip", "install", "--python", python, "--no-deps", *reqs]


def apt_dep(name: str = "numpy") -> ResolvedDep:
    return ResolvedDep(
        Dep(name), Source.APT, resolved_version="1.24", apt_pkg="python3-numpy"
    )


def pip_dep(name: str = "rich") -> ResolvedDep:
    return ResolvedDep(Dep(name, ">=13"), Source.PIP, resolved_version="13.7.0")


def test_execute_dry_run_prints_commands(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    plan = Plan(apt=[apt_dep()], pip=[pip_dep()])
    assert execute(plan, tmp_path / "venv", dry_run=True, runner=fake_uv) is False

    out = capsys.readouterr().out
    assert "sudo apt-get install -y python3-numpy" in out
    assert " ".join(install_cmd(tmp_path, "rich==13.7.0", "pygments==2.18.0")) in out


def test_execute_installs_missing_apt_and_pip_then_writes_lock(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    manifest = tmp_path / "petal.toml"
    manifest.write_text('[workspace]\nros_distro = "humble"\n', encoding="utf-8")
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if cmd[:2] == ["dpkg-query", "-W"]:
            return completed(cmd, returncode=1)
        if cmd[:3] == ["uv", "pip", "list"]:
            return completed(cmd, "[]")
        if cmd[:3] == ["uv", "pip", "compile"]:
            return compiled(cmd, kwargs)
        return completed(cmd)

    assert (
        execute(
            Plan(apt=[apt_dep()], pip=[pip_dep()]),
            tmp_path / "venv",
            lock_path=tmp_path / "petal.lock",
            stamp=lock_stamp(manifest, []),
            runner=runner,
            install_runner=runner,
            assume_yes=True,
        )
        is True
    )

    assert ["sudo", "apt-get", "install", "-y", "python3-numpy"] in calls
    assert install_cmd(tmp_path, "rich==13.7.0", "pygments==2.18.0") in calls
    lock = (tmp_path / "petal.lock").read_text(encoding="utf-8")
    assert 'manifest_hash = "sha256:' in lock
    assert 'name = "numpy"' in lock
    assert 'source = "apt"' in lock
    assert 'apt_pkg = "python3-numpy"' in lock
    assert 'name = "rich"' in lock
    assert 'version = "13.7.0"' in lock
    out = capsys.readouterr().out
    assert "APT: installing python3-numpy" in out
    assert "PIP: installing rich==13.7.0, pygments==2.18.0" in out
    assert "lock: wrote" in out


def test_execute_skips_installed_apt(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if cmd[:2] == ["dpkg-query", "-W"]:
            return completed(cmd, "install ok installed")
        return completed(cmd)

    assert execute(Plan(apt=[apt_dep()]), tmp_path / "venv", runner=runner) is True
    assert ["sudo", "apt-get", "install", "-y", "python3-numpy"] not in calls
    assert "petal: all dependencies already satisfied" in capsys.readouterr().out


def test_execute_prints_noop_for_empty_plan(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert execute(Plan(), tmp_path / "venv") is True
    assert "petal: no dependencies to install" in capsys.readouterr().out


def test_execute_prints_distro_noop(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    dep = ResolvedDep(Dep("rclpy"), Source.DISTRO, resolved_version="3.3.7")
    assert execute(Plan(distro=[dep]), tmp_path / "venv") is True
    assert "petal: all dependencies already satisfied" in capsys.readouterr().out


def test_write_lock_serializes_resolved_deps(tmp_path: Path) -> None:
    manifest = tmp_path / "petal.toml"
    manifest.write_text("[deps]\n", encoding="utf-8")
    lock = tmp_path / "petal.lock"

    write_lock(lock, lock_stamp(manifest, []), [apt_dep(), pip_dep()])

    text = lock.read_text(encoding="utf-8")
    assert text.count("[[resolved]]") == 2
    assert 'source = "apt"' in text
    assert 'source = "pip"' in text


def test_execute_no_prompt_skips_install(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:2] == ["dpkg-query", "-W"]:
            return completed(cmd, returncode=1)
        if cmd[:3] in (["uv", "pip", "list"], ["uv", "pip", "compile"]):
            return fake_uv(cmd, **kwargs)
        calls.append(cmd)
        return completed(cmd)

    assert (
        execute(
            Plan(apt=[apt_dep()], pip=[pip_dep()]),
            tmp_path / "venv",
            runner=runner,
            install_runner=runner,
            assume_no=True,
        )
        is False
    )

    assert calls == []
    assert "install cancelled" in capsys.readouterr().out


def test_execute_skips_installed_pip_without_prompt(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if cmd[:3] == ["uv", "pip", "list"]:
            return completed(cmd, '[{"name":"rich","version":"13.7.0"}]')
        return completed(cmd)

    assert (
        execute(
            Plan(pip=[pip_dep()]),
            tmp_path / "venv",
            runner=runner,
            install_runner=runner,
        )
        is True
    )

    assert [
        "uv",
        "pip",
        "install",
        "--python",
        str(tmp_path / "venv" / "bin" / "python"),
        "rich==13.7.0",
    ] not in calls
    assert "petal: all dependencies already satisfied" in capsys.readouterr().out


def test_execute_uses_canonical_pip_identity_for_underscore_alias(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if cmd[:3] == ["uv", "pip", "list"]:
            return completed(cmd, '[{"name":"foo-bar","version":"1.0"}]')
        return completed(cmd)

    dep = ResolvedDep(Dep("foo_bar"), Source.PIP, resolved_version="1.0")
    assert execute(Plan(pip=[dep]), tmp_path / "venv", runner=runner) is True
    assert not any(cmd[:3] == ["uv", "pip", "install"] for cmd in calls)


def test_execute_noop_leaves_matching_lock_unchanged(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    manifest = tmp_path / "petal.toml"
    manifest.write_text("[deps]\n", encoding="utf-8")
    dep = pip_dep()
    write_lock(tmp_path / "petal.lock", lock_stamp(manifest, []), [dep])
    before = (tmp_path / "petal.lock").read_text(encoding="utf-8")

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:3] == ["uv", "pip", "list"]:
            return completed(cmd, '[{"name":"rich","version":"13.7.0"}]')
        return completed(cmd)

    assert (
        execute(
            Plan(pip=[dep]),
            tmp_path / "venv",
            lock_path=tmp_path / "petal.lock",
            stamp=lock_stamp(manifest, []),
            runner=runner,
            install_runner=runner,
        )
        is True
    )

    assert (tmp_path / "petal.lock").read_text(encoding="utf-8") == before
    assert "lock: unchanged" in capsys.readouterr().out


def test_execute_noop_writes_missing_lock(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    manifest = tmp_path / "petal.toml"
    manifest.write_text("[deps]\n", encoding="utf-8")
    dep = pip_dep()

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:3] == ["uv", "pip", "list"]:
            return completed(cmd, '[{"name":"rich","version":"13.7.0"}]')
        return completed(cmd)

    assert (
        execute(
            Plan(pip=[dep]),
            tmp_path / "venv",
            lock_path=tmp_path / "petal.lock",
            stamp=lock_stamp(manifest, []),
            runner=runner,
            install_runner=runner,
        )
        is True
    )

    assert (tmp_path / "petal.lock").exists()
    assert "lock: wrote" in capsys.readouterr().out


def test_execute_non_tty_requires_yes(tmp_path: Path) -> None:
    with pytest.raises(InstallerError, match="--yes"):
        execute(Plan(pip=[pip_dep()]), tmp_path / "venv", runner=fake_uv)


def test_execute_never_installs_system_provided_packages(
    tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    constraints = tmp_path / ".petal" / "constraints.txt"
    system = SystemView(
        lambda: SystemPython({"pygments": "2.18.0", "pyyaml": "6.0.1"}),
        constraints_path=constraints,
    )
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if cmd[:3] == ["uv", "pip", "list"]:
            # A copy left behind by an older petal that shadows the system one.
            return completed(cmd, '[{"name":"PyYAML","version":"6.0.2"}]')
        if cmd[:3] == ["uv", "pip", "compile"]:
            assert cmd[cmd.index("--constraints") + 1] == str(constraints)
            return compiled(cmd, kwargs)
        return completed(cmd)

    assert execute(
        Plan(pip=[pip_dep()]),
        tmp_path / "venv",
        runner=runner,
        install_runner=runner,
        assume_yes=True,
        system=system,
    )

    install = install_cmd(tmp_path, "rich==13.7.0")
    install[6:6] = ["--constraints", str(constraints)]
    assert calls[-1] == install
    out = capsys.readouterr().out
    assert "pyyaml 6.0.2, shadowing the system's 6.0.1" in out


def test_execute_reports_unresolvable_pip_closure(tmp_path: Path) -> None:
    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:3] == ["uv", "pip", "list"]:
            return completed(cmd, "[]")
        if cmd[:3] == ["uv", "pip", "compile"]:
            return subprocess.CompletedProcess(
                cmd, 1, stdout="", stderr="numpy>=2 and numpy==1.24.2 conflict"
            )
        raise AssertionError(f"must not run {cmd}")

    with pytest.raises(InstallerError, match="numpy>=2 and numpy==1.24.2"):
        execute(
            Plan(pip=[pip_dep()]),
            tmp_path / "venv",
            runner=runner,
            install_runner=runner,
            assume_yes=True,
        )


def test_execute_replans_when_apt_changes_the_system(tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    manifest = tmp_path / "petal.toml"
    manifest.write_text("[deps]\n", encoding="utf-8")
    # The deb being installed provides `yaml`, which was headed for PyPI.
    snapshots = [SystemPython(), SystemPython({"pyyaml": "6.0.1"})]
    system = SystemView(lambda: snapshots.pop(0), constraints_path=None)
    pyyaml = ResolvedDep(Dep("pyyaml"), Source.PIP, resolved_version="6.0.2")
    replanned = Plan(
        apt=[apt_dep()],
        pip=[pip_dep()],
        distro=[ResolvedDep(Dep("pyyaml"), Source.DISTRO, resolved_version="6.0.1")],
    )
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if cmd[:2] == ["dpkg-query", "-W"]:
            return completed(cmd, returncode=1)
        if cmd[:3] in (["uv", "pip", "list"], ["uv", "pip", "compile"]):
            return fake_uv(cmd, **kwargs)
        return completed(cmd)

    assert execute(
        Plan(apt=[apt_dep()], pip=[pip_dep(), pyyaml]),
        tmp_path / "venv",
        runner=runner,
        install_runner=runner,
        assume_yes=True,
        system=system,
        lock_path=tmp_path / "petal.lock",
        stamp=lock_stamp(manifest, []),
        replan=lambda: replanned,
    )

    assert calls[-1] == install_cmd(tmp_path, "rich==13.7.0", "pygments==2.18.0")
    lock = (tmp_path / "petal.lock").read_text(encoding="utf-8")
    assert 'name = "pyyaml"\nsource = "distro"' in lock


def test_execute_noop_rewrites_lock_when_stamp_changes(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    manifest = tmp_path / "petal.toml"
    manifest.write_text("[deps]\n", encoding="utf-8")
    dep = ResolvedDep(Dep("rclpy"), Source.DISTRO)
    old = lock_stamp(manifest, [])
    new = lock_stamp(manifest, [Dep("rclpy")])
    write_lock(tmp_path / "petal.lock", old, [dep])

    assert execute(
        Plan(distro=[dep]),
        tmp_path / "venv",
        runner=fake_uv,
        lock_path=tmp_path / "petal.lock",
        stamp=new,
    )

    assert f'dependency_hash = "{new.dependency_hash}"' in (
        tmp_path / "petal.lock"
    ).read_text(encoding="utf-8")
    assert "lock: wrote" in capsys.readouterr().out
