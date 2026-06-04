from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from petal import cli, env
from petal.models import Dep, ResolvedDep, Source
from petal.planner import Plan


def test_init_writes_manifest_and_creates_venv(monkeypatch, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    venv = tmp_path / ".petal" / "venv"
    monkeypatch.setattr(env, "detect_ros_distro", lambda: "humble")
    monkeypatch.setattr(env, "distro_python", lambda distro: Path("/usr/bin/python3.10"))
    monkeypatch.setattr(env, "python_version", lambda interpreter: "3.10")
    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)

    assert cli.main(["init", "--workspace", str(tmp_path)]) == 0
    manifest = (tmp_path / "petal.toml").read_text(encoding="utf-8")
    assert 'ros_distro = "humble"' in manifest
    assert 'python_version = "3.10"' in manifest
    assert "venv:" in capsys.readouterr().out


def test_sync_dry_run_orchestrates_resolution(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "petal.toml").write_text(
        "[workspace]\nros_distro = \"humble\"\npython_version = \"3.10\"\n\n[deps]\nrich = \">=13\"\n",
        encoding="utf-8",
    )
    venv = tmp_path / ".petal" / "venv"
    executed = {}

    monkeypatch.setattr(env, "ensure_venv", lambda workspace, distro: venv)
    monkeypatch.setattr(cli, "discover_workspace", lambda workspace: SimpleNamespace(deps=[]))

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

    monkeypatch.setattr(cli, "execute", fake_execute)

    assert cli.main(["sync", "--workspace", str(tmp_path), "--dry-run"]) == 0
    assert executed["venv"] == venv
    assert executed["dry_run"] is True
    assert executed["plan"].pip[0].resolved_version == "13.7.0"


def test_activate_prints_eval_snippet(monkeypatch, tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "petal.toml").write_text(
        '[workspace]\nros_distro = "humble"\npython_version = "3.10"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(env, "detect_ros_distro", lambda: "humble")
    monkeypatch.setattr(
        env,
        "activation_snippet",
        lambda workspace, distro, shell: f"export VIRTUAL_ENV={workspace}/.petal/venv\n",
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
    assert cli.main(["activate", "--workspace", str(tmp_path), "--shell", "fish"]) == 0
    assert captured["shell"] == "fish"


def test_status_exit_code_2_on_drift(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "petal.toml").write_text(
        "[workspace]\nros_distro = \"humble\"\npython_version = \"3.10\"\n",
        encoding="utf-8",
    )
    (tmp_path / ".petal" / "venv").mkdir(parents=True)
    monkeypatch.setattr(cli, "check_status", lambda workspace, venv: SimpleNamespace(ok=False))
    printed = {}
    monkeypatch.setattr(cli, "print_report", lambda report: printed.setdefault("called", True))

    assert cli.main(["status", "--workspace", str(tmp_path)]) == 2
    assert printed["called"] is True
