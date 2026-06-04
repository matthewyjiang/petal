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


def test_detect_ros_distro_from_opt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    monkeypatch.setattr(env, "distro_python", lambda distro: Path("/usr/bin/python3.10"))

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append([str(part) for part in cmd])
        if "-m" in cmd and "venv" in cmd:
            venv = Path(cmd[-1])
            (venv / "bin").mkdir(parents=True)
            (venv / "bin" / "python").write_text("", encoding="utf-8")
            (venv / "pyvenv.cfg").write_text("version = 3.10.12\n", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0)
        return subprocess.CompletedProcess(cmd, 0, stdout="3.10\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    venv = env.ensure_venv(ws, "humble")

    assert venv == ws / ".petal" / "venv"
    assert ["/usr/bin/python3.10", "-m", "venv", "--system-site-packages", str(venv)] in calls
    assert (venv / "COLCON_IGNORE").exists()
    activate = (ws / ".petal" / "activate").read_text(encoding="utf-8")
    assert "source " + str(ros_root / "humble" / "setup.bash") in activate
    assert "source .petal/venv/bin/activate" in activate


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
    monkeypatch.setattr(env, "distro_python", lambda distro: Path("/usr/bin/python3.10"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout="3.10\n", stderr=""))

    with pytest.raises(env.PetalEnvError, match="petal clean"):
        env.ensure_venv(ws, "humble")
