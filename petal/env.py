from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROS_ROOT = Path(os.environ.get("PETAL_ROS_ROOT", "/opt/ros"))


class PetalEnvError(RuntimeError):
    """Environment detection failed."""


def _ros_root() -> Path:
    return Path(os.environ.get("PETAL_ROS_ROOT", str(ROS_ROOT)))


def detect_ros_distro() -> str:
    env_distro = os.environ.get("ROS_DISTRO")
    if env_distro:
        return env_distro

    root = _ros_root()
    candidates = sorted(p.name for p in root.glob("*") if (p / "setup.bash").is_file())
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise PetalEnvError(
            "Multiple ROS distros found. Set ROS_DISTRO to one of: "
            + ", ".join(candidates)
        )
    raise PetalEnvError(
        "No ROS distro found. Source /opt/ros/<distro>/setup.bash or set ROS_DISTRO."
    )


def distro_python(distro: str) -> Path:
    distro_root = _ros_root() / distro
    lib_dirs = sorted((distro_root / "lib").glob("python3.*"))
    versions = [p.name.removeprefix("python") for p in lib_dirs if p.is_dir()]
    if not versions:
        raise PetalEnvError(
            f"Could not detect Python version under {distro_root / 'lib'}."
        )
    if len(versions) > 1:
        raise PetalEnvError(
            f"Multiple Python versions found for ROS {distro}: {', '.join(versions)}."
        )

    version = versions[0]
    interpreter = Path(f"/usr/bin/python{version}")
    if not interpreter.exists():
        raise PetalEnvError(
            f"ROS {distro} was built for Python {version}, but {interpreter} does not exist."
        )
    return interpreter


def venv_path(workspace_root: Path) -> Path:
    return workspace_root / ".petal" / "venv"


def _venv_python(venv: Path) -> Path:
    return venv / "bin" / "python"


def _venv_version(venv: Path) -> str | None:
    cfg = venv / "pyvenv.cfg"
    if not cfg.exists():
        return None
    for line in cfg.read_text(encoding="utf-8").splitlines():
        if line.startswith("version = "):
            return line.split("=", 1)[1].strip()
    return None


def _venv_uses_system_site_packages(venv: Path) -> bool:
    cfg = venv / "pyvenv.cfg"
    if not cfg.exists():
        return False
    for line in cfg.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip() == "include-system-site-packages":
            return value.strip().lower() == "true"
    return False


def python_version(interpreter: Path) -> str:
    proc = subprocess.run(
        [
            str(interpreter),
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc.stdout.strip()


def ensure_venv(workspace_root: Path, distro: str) -> Path:
    interpreter = distro_python(distro)
    expected_version = python_version(interpreter)
    venv = venv_path(workspace_root)

    if _venv_python(venv).exists():
        existing_version = _venv_version(venv)
        if existing_version and not existing_version.startswith(expected_version):
            raise PetalEnvError(
                "Existing petal venv Python version does not match ROS distro. "
                "Run `petal clean`, then `petal init`."
            )
        if not _venv_uses_system_site_packages(venv):
            raise PetalEnvError(
                "Existing petal venv does not include system site-packages. "
                "Run `petal clean`, then `petal init`."
            )
        (venv / "COLCON_IGNORE").touch()
        _write_activate(workspace_root, distro)
        return venv

    venv.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(interpreter), "-m", "venv", "--system-site-packages", str(venv)],
        check=True,
    )
    (venv / "COLCON_IGNORE").touch()
    _write_activate(workspace_root, distro)
    return venv


def _write_activate(workspace_root: Path, distro: str) -> Path:
    petal_dir = workspace_root / ".petal"
    petal_dir.mkdir(parents=True, exist_ok=True)
    activate = petal_dir / "activate"
    activate.write_text(
        "#!/usr/bin/env bash\n"
        "set -e\n"
        f"source {_ros_root() / distro / 'setup.bash'}\n"
        "source .petal/venv/bin/activate\n",
        encoding="utf-8",
    )
    activate.chmod(0o755)
    return activate


def _detect_shell() -> str:
    """Return shell name (bash/zsh/fish) from $SHELL, defaulting to bash."""
    shell_path = os.environ.get("SHELL", "")
    name = Path(shell_path).name
    if name in ("bash", "zsh", "fish"):
        return name
    return "bash"


def _ros_setup_for_shell(distro: str, shell: str) -> Path | None:
    """Return the best ROS setup file for the given shell, or None if none exist."""
    ros_dir = _ros_root() / distro
    if shell == "fish":
        candidates = ["setup.fish", "setup.bash"]
    elif shell == "zsh":
        candidates = ["setup.zsh", "setup.sh", "setup.bash"]
    else:
        # bash and anything else
        candidates = ["setup.bash", "setup.sh"]
    for name in candidates:
        path = ros_dir / name
        if path.exists():
            return path
    return None


def activation_snippet(
    workspace_root: Path, distro: str, shell: str | None = None
) -> str:
    """Return a shell snippet to activate the petal venv + ROS env (use: source <(petal activate))."""
    if shell is None:
        shell = _detect_shell()
    venv = venv_path(workspace_root)
    ros_setup = _ros_setup_for_shell(distro, shell)

    if shell == "fish":
        lines = [
            f'set -gx VIRTUAL_ENV "{venv}"',
            'fish_add_path "$VIRTUAL_ENV/bin"',
            "set -e PYTHONHOME",
        ]
        if ros_setup is not None and ros_setup.suffix == ".fish":
            lines.append(f"source {ros_setup}")
        elif ros_setup is not None:
            # fish can't source bash/sh; best effort note
            lines.append(f"# NOTE: source {ros_setup} in a bash shell first")
        return "\n".join(lines) + "\n"
    else:
        # bash / zsh / sh-compatible
        lines = [
            f'export VIRTUAL_ENV="{venv}"',
            'export PATH="$VIRTUAL_ENV/bin:$PATH"',
            "unset PYTHONHOME",
        ]
        if ros_setup is not None:
            lines.append(f"source {ros_setup}")
        return "\n".join(lines) + "\n"


def distro_provided_modules(distro: str) -> set[str]:
    interpreter = distro_python(distro)
    code = """
import pkgutil
mods = sorted({m.name for m in pkgutil.iter_modules()})
print('\\n'.join(mods))
"""
    env = os.environ.copy()
    ros_site = next((_ros_root() / distro / "lib").glob("python3.*"), None)
    if ros_site:
        site = ros_site / "site-packages"
        env["PYTHONPATH"] = str(site) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [str(interpreter), "-c", code],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    return {line for line in proc.stdout.splitlines() if line}


def current_python_version() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"
