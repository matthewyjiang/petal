from __future__ import annotations

from importlib import metadata
from pathlib import Path
from types import SimpleNamespace

from petal import cli, env, preflight
from petal.installer import InstallerError, write_lock
from petal.models import Dep, ResolvedDep, Source
from petal.planner import Plan


def _ok_preflight():
    return preflight.PreflightReport()


def test_init_writes_manifest_and_creates_venv(
    monkeypatch, tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    venv = tmp_path / ".petal" / "venv"
    monkeypatch.setattr(env, "detect_ros_distro", lambda: "humble")
    monkeypatch.setattr(
        env, "distro_python", lambda distro: Path("/usr/bin/python3.10")
    )
    monkeypatch.setattr(env, "python_version", lambda interpreter: "3.10")
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)

    assert cli.main(["init", "--workspace", str(tmp_path)]) == 0
    manifest = (tmp_path / "petal.toml").read_text(encoding="utf-8")
    assert 'ros_distro = "humble"' in manifest
    assert 'python_version = "3.10"' in manifest
    assert "venv:" in capsys.readouterr().out


def test_sync_dry_run_orchestrates_resolution(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    (tmp_path / "petal.toml").write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\nrich = ">=13"\n',
        encoding="utf-8",
    )
    venv = tmp_path / ".petal" / "venv"
    executed = {}

    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)
    monkeypatch.setattr(
        cli, "discover_workspace", lambda workspace: SimpleNamespace(deps=[])
    )

    class FakeManager:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["ros_distro"] == "humble"
            assert kwargs["venv"] == venv

        def resolve(self, dep: Dep) -> ResolvedDep:
            assert dep.name == "rich"
            return ResolvedDep(dep, Source.PIP, resolved_version="13.7.0")

    monkeypatch.setattr(cli, "ResolutionManager", FakeManager)
    monkeypatch.setattr(cli, "build_plan", lambda resolved: Plan(pip=resolved))

    def fake_execute(plan, got_venv, **kwargs):  # type: ignore[no-untyped-def]
        executed["plan"] = plan
        executed["venv"] = got_venv
        executed["dry_run"] = kwargs["dry_run"]
        return False

    monkeypatch.setattr(cli, "execute", fake_execute)

    assert cli.main(["sync", "--workspace", str(tmp_path), "--dry-run"]) == 0
    assert executed["venv"] == venv
    assert executed["dry_run"] is True
    assert executed["plan"].pip[0].resolved_version == "13.7.0"


def test_sync_uses_current_lock_without_resolving(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    manifest = tmp_path / "petal.toml"
    manifest.write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\nrich = ">=13"\n',
        encoding="utf-8",
    )
    venv = tmp_path / ".petal" / "venv"
    write_lock(
        tmp_path / "petal.lock",
        manifest,
        [ResolvedDep(Dep("rich", ">=13"), Source.PIP, resolved_version="13.7.0")],
    )
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)
    monkeypatch.setattr(
        cli, "discover_workspace", lambda workspace: SimpleNamespace(deps=[])
    )

    class FakeManager:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("sync should use the current lock")

    monkeypatch.setattr(cli, "ResolutionManager", FakeManager)

    executed = {}

    def fake_execute(plan, got_venv, **kwargs):  # type: ignore[no-untyped-def]
        executed["plan"] = plan
        return True

    monkeypatch.setattr(cli, "execute", fake_execute)

    assert cli.main(["sync", "--workspace", str(tmp_path)]) == 0
    assert executed["plan"].pip[0].resolved_version == "13.7.0"


def test_sync_falls_back_when_lock_is_corrupt(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    manifest = tmp_path / "petal.toml"
    manifest.write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\nrich = ">=13"\n',
        encoding="utf-8",
    )
    (tmp_path / "petal.lock").write_text("not toml = [", encoding="utf-8")
    venv = tmp_path / ".petal" / "venv"
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)
    monkeypatch.setattr(
        cli, "discover_workspace", lambda workspace: SimpleNamespace(deps=[])
    )

    resolved_names = []

    class FakeManager:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def preload(self):  # type: ignore[no-untyped-def]
            pass

        def resolve(self, dep: Dep) -> ResolvedDep:
            resolved_names.append(dep.name)
            return ResolvedDep(dep, Source.PIP, resolved_version="13.7.0")

    monkeypatch.setattr(cli, "ResolutionManager", FakeManager)
    monkeypatch.setattr(cli, "build_plan", lambda resolved: Plan(pip=resolved))
    monkeypatch.setattr(cli, "execute", lambda plan, got_venv, **kwargs: True)

    assert cli.main(["sync", "--workspace", str(tmp_path)]) == 0
    assert resolved_names == ["rich"]


def test_sync_reresolves_when_discovered_deps_change(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    manifest = tmp_path / "petal.toml"
    manifest.write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\nrich = ">=13"\n',
        encoding="utf-8",
    )
    venv = tmp_path / ".petal" / "venv"
    write_lock(
        tmp_path / "petal.lock",
        manifest,
        [ResolvedDep(Dep("rich", ">=13"), Source.PIP, resolved_version="13.7.0")],
    )
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)
    monkeypatch.setattr(
        cli,
        "discover_workspace",
        lambda workspace: SimpleNamespace(deps=[Dep("httpx")]),
    )

    resolved_names = []

    class FakeManager:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def preload(self):  # type: ignore[no-untyped-def]
            pass

        def resolve(self, dep: Dep) -> ResolvedDep:
            resolved_names.append(dep.name)
            return ResolvedDep(dep, Source.PIP, resolved_version="1.0")

    monkeypatch.setattr(cli, "ResolutionManager", FakeManager)
    monkeypatch.setattr(cli, "build_plan", lambda resolved: Plan(pip=resolved))
    monkeypatch.setattr(cli, "execute", lambda plan, got_venv, **kwargs: True)

    assert cli.main(["sync", "--workspace", str(tmp_path)]) == 0
    assert resolved_names == ["rich", "httpx"]


def test_sync_yes_and_no_flags_pass_prompt_overrides(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    (tmp_path / "petal.toml").write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\nrich = ">=13"\n',
        encoding="utf-8",
    )
    venv = tmp_path / ".petal" / "venv"
    calls = []
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)
    monkeypatch.setattr(
        cli, "discover_workspace", lambda workspace: SimpleNamespace(deps=[])
    )

    class FakeManager:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def resolve(self, dep: Dep) -> ResolvedDep:
            return ResolvedDep(dep, Source.PIP, resolved_version="13.7.0")

    monkeypatch.setattr(cli, "ResolutionManager", FakeManager)
    monkeypatch.setattr(cli, "build_plan", lambda resolved: Plan(pip=resolved))

    def fake_execute(plan, got_venv, **kwargs):  # type: ignore[no-untyped-def]
        calls.append((kwargs["assume_yes"], kwargs["assume_no"]))
        return True

    monkeypatch.setattr(cli, "execute", fake_execute)

    assert cli.main(["sync", "--workspace", str(tmp_path), "--yes"]) == 0
    assert cli.main(["sync", "--workspace", str(tmp_path), "--no"]) == 0
    assert calls == [(True, False), (False, True)]


def test_main_handles_keyboard_interrupt(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        cli, "_cmd_status", lambda args: (_ for _ in ()).throw(KeyboardInterrupt)
    )

    assert cli.main(["status"]) == 130
    assert "petal: cancelled" in capsys.readouterr().err


def test_activate_prints_eval_snippet(monkeypatch, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "petal.toml").write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(env, "detect_ros_distro", lambda: "humble")
    monkeypatch.setattr(
        env,
        "activation_snippet",
        lambda workspace, distro, shell: (
            f"export VIRTUAL_ENV={workspace}/.petal/venv\n"
        ),
    )
    assert cli.main(["activate", "--workspace", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "VIRTUAL_ENV" in out


def test_activate_passes_shell_flag(monkeypatch, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "petal.toml").write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(env, "detect_ros_distro", lambda: "humble")
    captured = {}

    def fake_snippet(workspace, distro, shell):  # type: ignore[no-untyped-def]
        captured["shell"] = shell
        return "snippet\n"

    monkeypatch.setattr(env, "activation_snippet", fake_snippet)
    assert cli.main(["activate", "--workspace", str(tmp_path), "--shell", "zsh"]) == 0
    assert captured["shell"] == "zsh"


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


def test_status_exit_code_2_on_drift(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    (tmp_path / "petal.toml").write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n',
        encoding="utf-8",
    )
    (tmp_path / ".petal" / "venv").mkdir(parents=True)
    monkeypatch.setattr(
        cli, "check_status", lambda workspace, venv: SimpleNamespace(ok=False)
    )
    printed = {}
    monkeypatch.setattr(
        cli, "print_report", lambda report: printed.setdefault("called", True)
    )

    assert cli.main(["status", "--workspace", str(tmp_path)]) == 2
    assert printed["called"] is True


def test_add_updates_manifest_and_syncs_single_dep(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    (tmp_path / "petal.toml").write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\n',
        encoding="utf-8",
    )
    venv = tmp_path / ".petal" / "venv"
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)

    class FakeManager:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            assert kwargs["ros_distro"] == "humble"
            assert kwargs["venv"] == venv

        def resolve(self, dep: Dep) -> ResolvedDep:
            assert dep.name == "rich"
            assert dep.version_spec == ">=13"
            assert dep.source_hint == Source.PIP
            return ResolvedDep(dep, Source.PIP, resolved_version="13.7.0")

    executed = {}
    monkeypatch.setattr(cli, "ResolutionManager", FakeManager)
    monkeypatch.setattr(cli, "build_plan", lambda resolved: Plan(pip=resolved))

    def fake_execute(plan, got_venv, **kwargs):  # type: ignore[no-untyped-def]
        executed["plan"] = plan
        executed["venv"] = got_venv
        executed["dry_run"] = kwargs["dry_run"]
        return True

    monkeypatch.setattr(cli, "execute", fake_execute)
    monkeypatch.setattr(
        cli, "_rewrite_lock", lambda *args: executed.setdefault("rewrote", True)
    )

    assert (
        cli.main(
            ["add", "rich", ">=13", "--pip", "--workspace", str(tmp_path), "--yes"]
        )
        == 0
    )
    assert 'rich = { pip = ">=13" }' in (tmp_path / "petal.toml").read_text(
        encoding="utf-8"
    )
    assert executed["venv"] == venv
    assert executed["dry_run"] is False
    assert executed["plan"].pip[0].resolved_version == "13.7.0"
    assert executed["rewrote"] is True


def test_add_apt_uses_spec_as_package(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    (tmp_path / "petal.toml").write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\n',
        encoding="utf-8",
    )
    venv = tmp_path / ".petal" / "venv"
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)

    class FakeManager:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def resolve(self, dep: Dep) -> ResolvedDep:
            assert dep.name == "python3-opencv"
            assert dep.source_hint == Source.APT
            return ResolvedDep(dep, Source.APT, apt_pkg="python3-opencv")

    monkeypatch.setattr(cli, "ResolutionManager", FakeManager)
    monkeypatch.setattr(cli, "build_plan", lambda resolved: Plan(apt=resolved))
    rewrites = {}
    monkeypatch.setattr(cli, "execute", lambda plan, venv, **kwargs: True)
    monkeypatch.setattr(
        cli, "_rewrite_lock", lambda *args: rewrites.setdefault("called", True)
    )

    assert (
        cli.main(
            ["add", "opencv", "python3-opencv", "--apt", "--workspace", str(tmp_path)]
        )
        == 0
    )
    assert 'opencv = { apt = "python3-opencv" }' in (tmp_path / "petal.toml").read_text(
        encoding="utf-8"
    )
    assert rewrites["called"] is True


def test_add_no_and_dry_run_do_not_update_manifest(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    (tmp_path / "petal.toml").write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\n',
        encoding="utf-8",
    )
    venv = tmp_path / ".petal" / "venv"
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)

    class FakeManager:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def resolve(self, dep: Dep) -> ResolvedDep:
            return ResolvedDep(dep, Source.PIP, resolved_version="13.7.0")

    monkeypatch.setattr(cli, "ResolutionManager", FakeManager)
    monkeypatch.setattr(cli, "build_plan", lambda resolved: Plan(pip=resolved))
    monkeypatch.setattr(cli, "execute", lambda plan, venv, **kwargs: False)
    monkeypatch.setattr(
        cli, "_rewrite_lock", lambda *args: (_ for _ in ()).throw(AssertionError)
    )

    assert cli.main(["add", "rich", "--workspace", str(tmp_path), "--no"]) == 0
    assert cli.main(["add", "httpx", "--workspace", str(tmp_path), "--dry-run"]) == 0
    manifest = (tmp_path / "petal.toml").read_text(encoding="utf-8")
    assert "rich" not in manifest
    assert "httpx" not in manifest


def test_add_cancel_does_not_update_manifest(
    monkeypatch, tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    (tmp_path / "petal.toml").write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        env, "ensure_venv", lambda workspace, distro: tmp_path / ".petal" / "venv"
    )

    class FakeManager:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            pass

        def resolve(self, dep: Dep) -> ResolvedDep:
            return ResolvedDep(dep, Source.PIP, resolved_version="13.7.0")

    monkeypatch.setattr(cli, "ResolutionManager", FakeManager)
    monkeypatch.setattr(cli, "build_plan", lambda resolved: Plan(pip=resolved))
    monkeypatch.setattr(
        cli,
        "execute",
        lambda plan, venv, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt),
    )

    assert cli.main(["add", "rich", "--workspace", str(tmp_path)]) == 130
    assert "rich" not in (tmp_path / "petal.toml").read_text(encoding="utf-8")
    assert "cancelled" in capsys.readouterr().err


def test_remove_updates_manifest_uninstalls_and_rewrites_lock(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    (tmp_path / "petal.toml").write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\nrich = ">=13"\n',
        encoding="utf-8",
    )
    venv = tmp_path / ".petal" / "venv"
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)
    calls = {}

    def fake_uninstall(name, got_venv, **kwargs):  # type: ignore[no-untyped-def]
        calls["uninstall"] = (name, got_venv, kwargs["dry_run"])

    def fake_rewrite_lock(workspace, manifest_path, distro, got_venv):  # type: ignore[no-untyped-def]
        calls["rewrite"] = (workspace, manifest_path, distro, got_venv)

    monkeypatch.setattr(cli, "uninstall", fake_uninstall)
    monkeypatch.setattr(cli, "_rewrite_lock", fake_rewrite_lock)

    assert cli.main(["remove", "rich", "--workspace", str(tmp_path)]) == 0
    assert "rich" not in (tmp_path / "petal.toml").read_text(encoding="utf-8")
    assert calls["uninstall"] == ("rich", venv, False)
    assert calls["rewrite"] == (tmp_path, tmp_path / "petal.toml", "humble", venv)


def test_remove_apt_entry_by_manifest_key_uninstalls_and_rewrites_lock(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    manifest = tmp_path / "petal.toml"
    manifest.write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\nopencv = { apt = "python3-opencv" }\n',
        encoding="utf-8",
    )
    venv = tmp_path / ".petal" / "venv"
    calls = {}
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)

    def fake_uninstall(name: str, got_venv: Path, *, dry_run: bool) -> None:
        calls["uninstall"] = (name, got_venv, dry_run)

    def fake_rewrite_lock(
        workspace: Path, manifest_path: Path, distro: str, got_venv: Path
    ) -> None:
        calls["rewrite"] = (workspace, manifest_path, distro, got_venv)

    monkeypatch.setattr(cli, "uninstall", fake_uninstall)
    monkeypatch.setattr(cli, "_rewrite_lock", fake_rewrite_lock)

    assert cli.main(["remove", "opencv", "--workspace", str(tmp_path)]) == 0
    manifest_text = manifest.read_text(encoding="utf-8")
    assert "opencv" not in manifest_text
    assert calls["uninstall"] == ("opencv", venv, False)
    assert calls["rewrite"] == (tmp_path, manifest, "humble", venv)


def test_remove_apt_package_name_is_not_treated_as_manifest_key(
    monkeypatch, tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    manifest = tmp_path / "petal.toml"
    manifest.write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\nopencv = { apt = "python3-opencv" }\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        env, "ensure_venv", lambda workspace, distro: tmp_path / ".petal" / "venv"
    )
    monkeypatch.setattr(
        cli, "uninstall", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError)
    )
    monkeypatch.setattr(
        cli,
        "_rewrite_lock",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError),
    )

    assert cli.main(["remove", "python3-opencv", "--workspace", str(tmp_path)]) == 0
    assert "not present" in capsys.readouterr().out
    assert "opencv" in manifest.read_text(encoding="utf-8")


def test_remove_uninstall_failure_preserves_manifest(
    monkeypatch, tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    manifest = tmp_path / "petal.toml"
    manifest.write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\nrich = ">=13"\n',
        encoding="utf-8",
    )
    venv = tmp_path / ".petal" / "venv"
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)

    def fake_uninstall(name: str, got_venv: Path, *, dry_run: bool) -> None:
        assert name == "rich"
        assert got_venv == venv
        assert dry_run is False
        raise InstallerError("uninstall failed")

    monkeypatch.setattr(cli, "uninstall", fake_uninstall)
    monkeypatch.setattr(
        cli,
        "_rewrite_lock",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError),
    )

    assert cli.main(["remove", "rich", "--workspace", str(tmp_path)]) == 1
    assert "rich" in manifest.read_text(encoding="utf-8")
    assert "petal: uninstall failed" in capsys.readouterr().err


def test_remove_single_quoted_manifest_key_does_not_rewrite_lock_on_remove_failure(
    monkeypatch, tmp_path: Path, capsys
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    manifest = tmp_path / "petal.toml"
    original = "[workspace]\nros_distro = 'humble'\npython_version = '3.10'\n\n[deps]\n'rich' = '>=13'\n"
    manifest.write_text(original, encoding="utf-8")
    venv = tmp_path / ".petal" / "venv"
    calls = {}
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)

    def fake_uninstall(name: str, got_venv: Path, *, dry_run: bool) -> None:
        calls["uninstall"] = (name, got_venv, dry_run)

    def fake_rewrite_lock(
        workspace: Path, manifest_path: Path, distro: str, got_venv: Path
    ) -> None:
        calls["rewrite"] = (workspace, manifest_path, distro, got_venv)

    monkeypatch.setattr(cli, "uninstall", fake_uninstall)
    monkeypatch.setattr(cli, "_rewrite_lock", fake_rewrite_lock)

    assert cli.main(["remove", "rich", "--workspace", str(tmp_path)]) == 1
    assert calls["uninstall"] == ("rich", venv, False)
    assert "rewrite" not in calls
    assert manifest.read_text(encoding="utf-8") == original
    assert (
        "petal: could not remove rich from petal.toml; lock not rewritten"
        in capsys.readouterr().err
    )


def test_remove_missing_dep_is_noop(monkeypatch, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    (tmp_path / "petal.toml").write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        env, "ensure_venv", lambda workspace, distro: tmp_path / ".petal" / "venv"
    )
    monkeypatch.setattr(
        cli, "uninstall", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError)
    )

    assert cli.main(["remove", "rich", "--workspace", str(tmp_path)]) == 0
    assert "not present" in capsys.readouterr().out


def test_remove_dry_run_uninstalls_without_mutating_manifest(
    monkeypatch, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(preflight, "check", _ok_preflight)
    manifest = tmp_path / "petal.toml"
    original = '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n\n[deps]\nrich = ">=13"\n'
    manifest.write_text(original, encoding="utf-8")
    venv = tmp_path / ".petal" / "venv"
    calls = {}
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)

    def fake_uninstall(name: str, got_venv: Path, *, dry_run: bool) -> None:
        calls["uninstall"] = (name, got_venv, dry_run)

    monkeypatch.setattr(cli, "uninstall", fake_uninstall)
    monkeypatch.setattr(
        cli,
        "_rewrite_lock",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError),
    )

    assert cli.main(["remove", "rich", "--workspace", str(tmp_path), "--dry-run"]) == 0
    assert manifest.read_text(encoding="utf-8") == original
    assert calls["uninstall"] == ("rich", venv, True)
