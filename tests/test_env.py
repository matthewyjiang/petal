from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from petal import env


def make_ros(root: Path, distro: str = "humble", py: str = "3.10") -> Path:
    ros = root / distro
    (ros / "lib" / f"python{py}" / "site-packages").mkdir(parents=True)
    (ros / "setup.bash").write_text("", encoding="utf-8")
    return ros


def test_detect_ros_distro_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROS_DISTRO", "jazzy")
    assert env.detect_ros_distro() == "jazzy"


def test_detect_ros_distro_from_opt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ROS_DISTRO", raising=False)
    monkeypatch.setenv("PETAL_ROS_ROOT", str(tmp_path))
    make_ros(tmp_path, "humble")
    assert env.detect_ros_distro() == "humble"


def test_distro_python_requires_exact_usr_interpreter(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PETAL_ROS_ROOT", str(tmp_path))
    make_ros(tmp_path, "humble", "3.10")
    monkeypatch.setattr(Path, "exists", lambda self: str(self) == "/usr/bin/python3.10")
    assert env.distro_python("humble") == Path("/usr/bin/python3.10")


def test_ensure_venv_uses_system_site_packages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ros_root = tmp_path / "ros"
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("PETAL_ROS_ROOT", str(ros_root))
    make_ros(ros_root, "humble", "3.10")
    monkeypatch.setattr(
        env, "distro_python", lambda distro: Path("/usr/bin/python3.10")
    )

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append([str(part) for part in cmd])
        if "-m" in cmd and "venv" in cmd:
            venv = Path(cmd[-1])
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python").write_text("", encoding="utf-8")
            (venv / "pyvenv.cfg").write_text(
                "version = 3.10.12\ninclude-system-site-packages = true\n",
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0, stdout="3.10\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    venv = env.ensure_venv(ws, "humble")

    assert venv == ws / ".petal" / "venv"
    assert [
        "/usr/bin/python3.10",
        "-m",
        "venv",
        "--system-site-packages",
        str(venv),
    ] in calls
    assert (venv / "COLCON_IGNORE").exists()
    activate = (ws / ".petal" / "activate").read_text(encoding="utf-8")
    assert "set -e" not in activate
    assert "must be sourced, not executed" in activate
    assert "exit 2" in activate
    assert f"_petal_ws={ws}" in activate
    assert "${ZSH_VERSION:-}" in activate
    assert "${BASH_VERSION:-}" in activate
    assert f"_petal_ros_dir={ros_root / 'humble'}" in activate
    assert "setup.${_petal_shell}" in activate
    assert '. "${_petal_ws}/.petal/venv/bin/activate" || return $?' in activate
    assert 'cd "${_petal_ws}" || return $?' in activate


def test_activation_snippet_bash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ros_root = tmp_path / "ros"
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("PETAL_ROS_ROOT", str(ros_root))
    setup = ros_root / "humble" / "setup.bash"
    setup.parent.mkdir(parents=True)
    setup.write_text("", encoding="utf-8")

    snippet = env.activation_snippet(ws, "humble", shell="bash")
    lines = snippet.splitlines()
    assert lines == [
        "unset PYTHONHOME",
        f". {setup}",
        f'export VIRTUAL_ENV="{ws / ".petal" / "venv"}"',
        'export PATH="$VIRTUAL_ENV/bin:$PATH"',
    ]


def test_activation_snippet_zsh_prefers_setup_zsh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ros_root = tmp_path / "ros"
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("PETAL_ROS_ROOT", str(ros_root))
    ros_dir = ros_root / "humble"
    ros_dir.mkdir(parents=True)
    (ros_dir / "setup.bash").write_text("", encoding="utf-8")
    setup_zsh = ros_dir / "setup.zsh"
    setup_zsh.write_text("", encoding="utf-8")

    snippet = env.activation_snippet(ws, "humble", shell="zsh")
    assert "export VIRTUAL_ENV=" in snippet
    assert "export PATH=" in snippet
    assert f". {setup_zsh}" in snippet
    assert "setup.bash" not in snippet


def test_activation_snippet_zsh_fallback_to_bash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ros_root = tmp_path / "ros"
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("PETAL_ROS_ROOT", str(ros_root))
    ros_dir = ros_root / "humble"
    ros_dir.mkdir(parents=True)
    setup_bash = ros_dir / "setup.bash"
    setup_bash.write_text("", encoding="utf-8")

    snippet = env.activation_snippet(ws, "humble", shell="zsh")
    assert f". {setup_bash}" in snippet


def test_activation_snippet_auto_detects_shell(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ros_root = tmp_path / "ros"
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("PETAL_ROS_ROOT", str(ros_root))
    monkeypatch.setenv("SHELL", "/bin/zsh")
    (ros_root / "humble").mkdir(parents=True)

    snippet = env.activation_snippet(ws, "humble", shell=None)
    # zsh uses same bash-style exports
    assert "export VIRTUAL_ENV" in snippet


def test_activation_snippet_without_ros_setup_still_activates_venv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ros_root = tmp_path / "ros"
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("PETAL_ROS_ROOT", str(ros_root))
    (ros_root / "humble").mkdir(parents=True)

    snippet = env.activation_snippet(ws, "humble", shell="bash")

    assert f'export VIRTUAL_ENV="{ws / ".petal" / "venv"}"' in snippet
    assert 'export PATH="$VIRTUAL_ENV/bin:$PATH"' in snippet
    assert "unset PYTHONHOME" in snippet
    assert ". " not in snippet


def test_ensure_venv_rejects_version_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ros_root = tmp_path / "ros"
    ws = tmp_path / "ws"
    venv = ws / ".petal" / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("", encoding="utf-8")
    (venv / "pyvenv.cfg").write_text("version = 3.11.1\n", encoding="utf-8")
    monkeypatch.setenv("PETAL_ROS_ROOT", str(ros_root))
    make_ros(ros_root, "humble", "3.10")
    monkeypatch.setattr(
        env, "distro_python", lambda distro: Path("/usr/bin/python3.10")
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 0, stdout="3.10\n", stderr=""
        ),
    )

    with pytest.raises(env.PetalEnvError, match="petal clean"):
        env.ensure_venv(ws, "humble")


def test_ensure_venv_rejects_missing_system_site_packages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ros_root = tmp_path / "ros"
    ws = tmp_path / "ws"
    venv = ws / ".petal" / "venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python").write_text("", encoding="utf-8")
    (venv / "pyvenv.cfg").write_text(
        "version = 3.10.12\ninclude-system-site-packages = false\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PETAL_ROS_ROOT", str(ros_root))
    make_ros(ros_root, "humble", "3.10")
    monkeypatch.setattr(
        env, "distro_python", lambda distro: Path("/usr/bin/python3.10")
    )
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess(
            a[0], 0, stdout="3.10\n", stderr=""
        ),
    )

    with pytest.raises(env.PetalEnvError, match="system site-packages"):
        env.ensure_venv(ws, "humble")
