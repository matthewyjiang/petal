"""CLI behavior against a scripted machine (see tests/fake_machine.py)."""

from __future__ import annotations

import subprocess
from dataclasses import replace
from importlib import metadata
from pathlib import Path

import pytest
from fake_machine import Deb, FakeMachine, workspace

from petal import cli

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 only
    import tomli as tomllib


def petal(machine: FakeMachine, ws: Path, *args: str) -> int:
    return cli.main([*args, "--workspace", str(ws)], host=machine.host())


def lock_entries(ws: Path) -> dict[str, dict[str, str]]:
    data = tomllib.loads((ws / "petal.lock").read_text(encoding="utf-8"))
    return {entry["name"]: entry for entry in data["resolved"]}


def ros_machine() -> FakeMachine:
    """Humble-ish: rclpy and system requests; numpy via rosdep/apt; rich on PyPI."""
    return FakeMachine(
        system={"requests": "2.32.3", "pygments": "2.18.0"},
        modules={"rclpy", "requests", "pygments"},
        rosdep={"python3-numpy": ("apt", "python3-numpy")},
        apt={
            "python3-numpy": Deb("1:1.24.2-1ubuntu1", provides={"numpy": "1.24.2"}),
        },
        pypi={
            "rich": ("13.7.0", ["markdown-it-py", "pygments"]),
            "markdown-it-py": ("3.0.0", []),
            "httpx": ("0.28.1", ["idna"]),
            "idna": ("3.10", []),
            "urllib3": ("2.8.0", []),
        },
    )


def app_workspace(
    root: Path, requires: tuple[str, ...] = ("requests>=2", "rich")
) -> Path:
    return workspace(
        root, packages={"pkg_a": (["rclpy", "python3-numpy"], list(requires))}
    )


# --- sync --------------------------------------------------------------------


def test_sync_installs_apt_and_pypi_without_shadowing_the_system(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)

    assert petal(machine, ws, "sync", "--yes") == 0

    assert machine.apt_installed == {"python3-numpy"}
    # pygments and requests come from the system, so only rich's own deps land.
    assert machine.venv == {"rich": "13.7.0", "markdown-it-py": "3.0.0"}
    entries = lock_entries(ws)
    assert entries["rclpy"]["source"] == "distro"
    assert entries["requests"]["source"] == "distro"
    assert entries["python3-numpy"]["apt_pkg"] == "python3-numpy"
    assert entries["rich"] == {
        "name": "rich",
        "source": "pip",
        "hint": "pip",
        "version": "13.7.0",
    }
    # The lock pins the whole closure: what rich pulls in, from PyPI or the system.
    assert entries["markdown-it-py"] == {
        "name": "markdown-it-py",
        "source": "pip",
        "version": "3.0.0",
        "transitive": True,
    }
    assert entries["pygments"] == {
        "name": "pygments",
        "source": "distro",
        "transitive": True,
    }
    assert "lock: wrote" in capsys.readouterr().out


def test_second_sync_reuses_the_lock_and_changes_nothing(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)
    petal(machine, ws, "sync", "--yes")
    lock = (ws / "petal.lock").read_bytes()
    machine.commands.clear()

    assert petal(machine, ws, "sync", "--yes") == 0

    assert not machine.ran("rosdep") and not machine.ran("uv", "pip", "install")
    assert (ws / "petal.lock").read_bytes() == lock
    assert "lock: unchanged" in capsys.readouterr().out


def test_dry_run_prints_the_plan_and_changes_nothing(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)

    assert petal(machine, ws, "sync", "--dry-run") == 0

    out = capsys.readouterr().out
    assert "sudo apt-get install -y python3-numpy" in out
    assert "--no-deps" in out and "rich==13.7.0" in out
    assert not machine.apt_installed and not machine.venv
    assert not (ws / "petal.lock").exists()


def test_no_flag_prints_changes_without_installing(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)

    assert petal(machine, ws, "sync", "--no") == 0

    assert "install cancelled" in capsys.readouterr().out
    assert not machine.apt_installed and not machine.venv


def test_sync_requires_confirmation_without_a_terminal(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)

    assert petal(machine, ws, "sync") == 1
    assert "rerun with --yes" in capsys.readouterr().err


def test_sync_reresolves_when_the_lock_is_corrupt(tmp_path):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)
    (ws / "petal.lock").write_text("not toml = [", encoding="utf-8")

    assert petal(machine, ws, "sync", "--yes") == 0
    assert lock_entries(ws)["rich"]["version"] == "13.7.0"


def test_sync_reresolves_when_workspace_deps_change(tmp_path):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)
    petal(machine, ws, "sync", "--yes")
    (ws / "src" / "pkg_a" / "setup.cfg").write_text(
        "[options]\ninstall_requires =\n    rich\n    httpx\n", encoding="utf-8"
    )

    assert petal(machine, ws, "sync", "--yes") == 0

    assert machine.venv["httpx"] == "0.28.1"
    assert "httpx" in lock_entries(ws)


def test_sync_reresolves_when_the_system_starts_providing_a_locked_pip_dep(tmp_path):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)
    petal(machine, ws, "sync", "--yes")
    machine.system["rich"] = "13.9.4"  # e.g. someone installed python3-rich

    assert petal(machine, ws, "sync", "--yes") == 0

    assert lock_entries(ws)["rich"]["source"] == "distro"


def test_resolving_again_keeps_locked_versions(tmp_path):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)
    petal(machine, ws, "sync", "--yes")
    machine.pypi["rich"] = ("14.0.0", ["markdown-it-py", "pygments"])
    machine.pypi["markdown-it-py"] = ("4.0.0", [])

    assert petal(machine, ws, "add", "httpx", "--yes") == 0

    entries = lock_entries(ws)
    assert entries["rich"]["version"] == "13.7.0"
    assert entries["markdown-it-py"]["version"] == "3.0.0"
    assert machine.venv["rich"] == "13.7.0"


def test_requirement_the_system_cannot_satisfy_fails_with_reason(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine = ros_machine()
    machine.system["urllib3"] = "2.3.0"
    ws = app_workspace(tmp_path, ("urllib3>=2.5",))

    assert petal(machine, ws, "sync", "--yes") == 1

    err = capsys.readouterr().err
    assert "the system provides urllib3 2.3.0" in err
    assert not machine.venv and not machine.apt_installed


def test_unresolvable_rosdep_key_fails_before_installing(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine = ros_machine()
    ws = workspace(tmp_path, packages={"pkg_a": (["python3-numpy", "my_typo_dep"], [])})

    assert petal(machine, ws, "sync", "--yes") == 1

    err = capsys.readouterr().err
    assert "my_typo_dep (from pkg_a)" in err and "[overrides]" in err
    assert not machine.apt_installed
    assert not (ws / "petal.lock").exists()


def test_deb_installed_by_apt_satisfies_a_pypi_bound_requirement(tmp_path):  # type: ignore[no-untyped-def]
    machine = ros_machine()
    machine.rosdep["python3-mdurl"] = ("apt", "python3-mdurl")
    machine.apt["python3-mdurl"] = Deb("0.1.2-1", provides={"mdurl": "0.1.2"})
    machine.pypi["mdurl"] = ("0.1.2", [])
    ws = workspace(tmp_path, packages={"pkg_a": (["python3-mdurl"], ["mdurl"])})

    assert petal(machine, ws, "sync", "--yes") == 0

    assert "mdurl" not in machine.venv
    entries = lock_entries(ws)
    assert entries["mdurl"]["source"] == "distro"
    assert entries["python3-mdurl"]["source"] == "apt"


# --- frozen --------------------------------------------------------------------


def test_frozen_on_a_fresh_machine_installs_the_lock_as_recorded(tmp_path):  # type: ignore[no-untyped-def]
    author, ws = ros_machine(), app_workspace(tmp_path / "a")
    petal(author, ws, "sync", "--yes")
    lock = (ws / "petal.lock").read_bytes()
    # Released since the lock was written.
    author.pypi["rich"] = ("14.0.0", ["markdown-it-py", "pygments"])
    author.pypi["markdown-it-py"] = ("4.0.0", [])

    ci = ros_machine()
    ci.pypi = author.pypi
    assert petal(ci, ws, "sync", "--frozen") == 0

    assert not ci.ran("rosdep") and not ci.ran("uv", "pip", "compile")
    assert ci.apt_installed == {"python3-numpy"}
    assert ci.venv == author.venv
    assert (ws / "petal.lock").read_bytes() == lock


def test_frozen_fails_when_inputs_changed(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)
    petal(machine, ws, "sync", "--yes")
    (ws / "petal.toml").write_text(
        (ws / "petal.toml")
        .read_text(encoding="utf-8")
        .replace("[deps]", '[deps]\nhttpx = "*"'),
        encoding="utf-8",
    )

    assert petal(machine, ws, "sync", "--frozen") == 1
    assert "out of date with petal.toml" in capsys.readouterr().err


def test_frozen_fails_when_the_lock_does_not_fit_the_system(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)
    petal(machine, ws, "sync", "--yes")
    machine.system["rich"] = "13.9.4"

    assert petal(machine, ws, "sync", "--frozen") == 1
    assert "the system now provides 13.9.4" in capsys.readouterr().err


def test_frozen_fails_when_a_locked_system_dep_is_missing(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)
    petal(machine, ws, "sync", "--yes")

    bare = ros_machine()
    del bare.system["requests"]
    assert petal(bare, ws, "sync", "--frozen") == 1
    assert "requests>=2 is locked to the system" in capsys.readouterr().err


# --- add / remove -----------------------------------------------------------------


def test_add_records_the_dep_and_syncs(tmp_path):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)

    assert petal(machine, ws, "add", "httpx", ">=0.27", "--yes") == 0

    deps = tomllib.loads((ws / "petal.toml").read_text(encoding="utf-8"))["deps"]
    assert deps == {"httpx": ">=0.27"}
    assert machine.venv["httpx"] == "0.28.1"
    assert machine.apt_installed == {"python3-numpy"}  # the rest of the workspace too
    assert lock_entries(ws)["httpx"]["version"] == "0.28.1"


def test_add_pip_may_shadow_a_system_package_on_purpose(tmp_path):  # type: ignore[no-untyped-def]
    machine = ros_machine()
    machine.pypi["requests"] = ("2.34.2", [])
    ws = workspace(tmp_path)

    assert petal(machine, ws, "add", "requests", ">=2.34", "--pip", "--yes") == 0

    assert machine.venv["requests"] == "2.34.2"
    constraints = (ws / ".petal" / "constraints.txt").read_text(encoding="utf-8")
    assert "requests" not in constraints and "pygments==2.18.0" in constraints


def test_add_apt_uses_the_given_package(tmp_path):  # type: ignore[no-untyped-def]
    machine = ros_machine()
    machine.apt["python3-opencv"] = Deb("4.5.4+dfsg-9ubuntu4")
    ws = workspace(tmp_path)

    assert petal(machine, ws, "add", "opencv", "python3-opencv", "--apt", "--yes") == 0

    deps = tomllib.loads((ws / "petal.toml").read_text(encoding="utf-8"))["deps"]
    assert deps == {"opencv": {"apt": "python3-opencv"}}
    assert "python3-opencv" in machine.apt_installed


@pytest.mark.parametrize(
    ("name", "flag", "keys"),
    [
        ("nope-xyz", "--yes", []),  # the new dep does not resolve
        ("httpx", "--yes", ["python3-numpy", "my_typo_dep"]),  # the workspace does not
        ("httpx", "--no", []),
        ("httpx", "--dry-run", []),
    ],
)
def test_add_leaves_petal_toml_untouched_unless_it_succeeds(tmp_path, name, flag, keys):  # type: ignore[no-untyped-def]
    machine = ros_machine()
    ws = workspace(tmp_path, packages={"pkg_a": (keys, [])})
    before = (ws / "petal.toml").read_bytes()

    petal(machine, ws, "add", name, flag)

    assert (ws / "petal.toml").read_bytes() == before
    assert not (ws / "petal.lock").exists()
    assert not machine.venv


def test_add_interrupted_during_install_restores_petal_toml(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), workspace(tmp_path)
    before = (ws / "petal.toml").read_bytes()

    def interrupt(cmd):  # type: ignore[no-untyped-def]
        raise KeyboardInterrupt

    host = replace(machine.host(), install_runner=interrupt)
    assert cli.main(["add", "httpx", "--yes", "--workspace", str(ws)], host=host) == 130

    assert (ws / "petal.toml").read_bytes() == before
    assert "petal: cancelled" in capsys.readouterr().err


def test_remove_drops_the_dep_uninstalls_and_rewrites_the_lock(tmp_path):  # type: ignore[no-untyped-def]
    machine = ros_machine()
    ws = workspace(tmp_path, deps='httpx = "*"\nrich = "*"\n')
    petal(machine, ws, "sync", "--yes")

    assert petal(machine, ws, "remove", "httpx") == 0

    deps = tomllib.loads((ws / "petal.toml").read_text(encoding="utf-8"))["deps"]
    assert deps == {"rich": "*"}
    assert "httpx" not in machine.venv
    assert "httpx" not in lock_entries(ws) and "rich" in lock_entries(ws)


def test_remove_matches_the_manifest_key_not_the_apt_package(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine = ros_machine()
    machine.apt["python3-opencv"] = Deb("4.5.4-1")
    ws = workspace(tmp_path, deps='opencv = { apt = "python3-opencv" }\n')

    assert petal(machine, ws, "remove", "python3-opencv") == 0
    assert "not present" in capsys.readouterr().out
    assert petal(machine, ws, "remove", "opencv") == 0
    assert "opencv" not in (ws / "petal.toml").read_text(encoding="utf-8")


def test_remove_keeps_petal_toml_when_uninstall_fails(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine = ros_machine()
    ws = workspace(tmp_path, deps='rich = "*"\n')
    before = (ws / "petal.toml").read_bytes()
    machine.uninstall_fails = True

    assert petal(machine, ws, "remove", "rich") == 1
    assert (ws / "petal.toml").read_bytes() == before
    assert "uninstall failed" in capsys.readouterr().err


def test_remove_dry_run_changes_nothing(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine = ros_machine()
    ws = workspace(tmp_path, deps='rich = "*"\n')
    before = (ws / "petal.toml").read_bytes()

    assert petal(machine, ws, "remove", "rich", "--dry-run") == 0
    assert (ws / "petal.toml").read_bytes() == before
    assert "uv pip uninstall" in capsys.readouterr().out
    assert not machine.ran("uv", "pip", "uninstall")


# --- init / status ------------------------------------------------------------------


def test_init_writes_the_manifest_and_creates_the_venv(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine = ros_machine()

    assert petal(machine, tmp_path, "init") == 0

    manifest = tomllib.loads((tmp_path / "petal.toml").read_text(encoding="utf-8"))
    assert manifest["workspace"] == {"ros_distro": "humble"}
    assert (tmp_path / ".petal" / "venv").is_dir()
    assert f"initialized {tmp_path}" in capsys.readouterr().out


def test_status_reports_drift_with_exit_code_2(tmp_path, capsys):  # type: ignore[no-untyped-def]
    machine, ws = ros_machine(), app_workspace(tmp_path)
    petal(machine, ws, "sync", "--yes")
    assert petal(machine, ws, "status") == 0

    machine.venv["rich"] = "14.0.0"

    assert petal(machine, ws, "status") == 2
    assert "rich (14.0.0 != 13.7.0)" in capsys.readouterr().out


# --- activate / agent skill ----------------------------------------------------


def test_activate_sources_the_workspace_script(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    script = tmp_path / ".petal" / "activate"
    script.parent.mkdir()
    script.write_text("", encoding="utf-8")

    assert cli.main(["activate", "--workspace", str(tmp_path)]) == 0
    assert capsys.readouterr().out == f". {script}\n"
    assert cli.main(["activate", "--workspace", str(tmp_path), "--shell", "zsh"]) == 0
    assert capsys.readouterr().out == f"PETAL_SHELL=zsh . {script}\n"


def test_activate_requires_init(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    assert cli.main(["activate", "--workspace", str(tmp_path)]) == 1

    # `source <(petal activate)` only sees stdout, so that must fail too.
    sourced = subprocess.run(
        ["bash", "-c", 'source <(cat); echo "status=$?"'],
        input=capsys.readouterr().out,
        capture_output=True,
        text=True,
        check=True,
    )
    assert sourced.stdout == "status=1\n"
    assert "run `petal init` first" in sourced.stderr


def test_install_agent_skill_copies_skill(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    target = tmp_path / "skills"

    assert cli.main(["install-agent-skill", "--target", str(target)]) == 0

    installed = target / "petal-cli" / "SKILL.md"
    assert installed.exists()
    assert "name: petal-cli" in installed.read_text(encoding="utf-8")
    assert str(installed.parent) in capsys.readouterr().out


def test_install_agent_skill_existing_requires_force(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    target = tmp_path / "skills"
    existing = target / "petal-cli"
    existing.mkdir(parents=True)
    (existing / "SKILL.md").write_text("custom", encoding="utf-8")

    assert cli.main(["install-agent-skill", "--target", str(target)]) == 0
    assert (existing / "SKILL.md").read_text(encoding="utf-8") == "custom"
    assert "--force" in capsys.readouterr().out

    assert cli.main(["install-agent-skill", "--target", str(target), "--force"]) == 0
    assert "name: petal-cli" in (existing / "SKILL.md").read_text(encoding="utf-8")


def _raise_package_not_found(_name):  # type: ignore[no-untyped-def]
    raise metadata.PackageNotFoundError("petal-ros")


def test_skill_source_falls_back_to_source_tree(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(cli.metadata, "distribution", _raise_package_not_found)

    source = cli._skill_source()

    assert source.name == "petal-cli"
    assert (source / "SKILL.md").is_file()


def test_install_agent_skill_uses_source_tree_when_package_missing(  # type: ignore[no-untyped-def]
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(cli.metadata, "distribution", _raise_package_not_found)
    target = tmp_path / "skills"

    assert cli.main(["install-agent-skill", "--target", str(target)]) == 0

    installed = target / "petal-cli" / "SKILL.md"
    assert installed.exists()
    assert "name: petal-cli" in installed.read_text(encoding="utf-8")


def test_install_agent_skill_noop_skips_source_resolution(  # type: ignore[no-untyped-def]
    tmp_path: Path, monkeypatch, capsys
) -> None:
    target = tmp_path / "skills" / "petal-cli"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("custom", encoding="utf-8")

    def _fail() -> Path:
        raise AssertionError("source must not be resolved for an existing install")

    monkeypatch.setattr(cli, "_skill_source", _fail)

    assert cli.main(["install-agent-skill", "--target", str(tmp_path / "skills")]) == 0
    assert "already installed" in capsys.readouterr().out
    assert (target / "SKILL.md").read_text(encoding="utf-8") == "custom"
