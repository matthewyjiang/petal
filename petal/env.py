from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


class PetalEnvError(RuntimeError):
    """Environment detection failed."""


def ros_root() -> Path:
    """Directory holding ROS distros; PETAL_ROS_ROOT overrides it for tests."""
    return Path(os.environ.get("PETAL_ROS_ROOT", "/opt/ros"))


def detect_ros_distro() -> str:
    env_distro = os.environ.get("ROS_DISTRO")
    if env_distro:
        return env_distro

    root = ros_root()
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
    distro_root = ros_root() / distro
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
        capture_output=True,
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
        write_activate(workspace_root, distro)
        return venv

    venv.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [str(interpreter), "-m", "venv", "--system-site-packages", str(venv)],
        check=True,
    )
    (venv / "COLCON_IGNORE").touch()
    write_activate(workspace_root, distro)
    return venv


def write_activate(workspace_root: Path, distro: str) -> Path:
    """Write `.petal/activate`, the one script that activates ROS + the venv.

    Sourced directly (`. .petal/activate`) or via `source <(petal activate)`.
    """
    petal_dir = workspace_root / ".petal"
    petal_dir.mkdir(parents=True, exist_ok=True)
    activate = petal_dir / "activate"
    workspace = workspace_root.resolve()
    ros_dir = ros_root() / distro
    activate.write_text(
        "# Petal workspace activation\n"
        'if [ -n "${BASH_VERSION:-}" ] && [ "${BASH_SOURCE[0]}" = "$0" ]; then\n'
        '  echo "petal: this script must be sourced, not executed" >&2\n'
        '  echo "petal: run: . .petal/activate" >&2\n'
        "  exit 2\n"
        "fi\n"
        'if [ -n "${ZSH_VERSION:-}" ] && case ${ZSH_EVAL_CONTEXT:-} in *:file*) false;; *) true;; esac; then\n'
        '  echo "petal: this script must be sourced, not executed" >&2\n'
        '  echo "petal: run: . .petal/activate" >&2\n'
        "  exit 2\n"
        "fi\n"
        "\n"
        f"_petal_ws={shlex.quote(str(workspace))}\n"
        f"_petal_ros_dir={shlex.quote(str(ros_dir))}\n"
        '_petal_shell="${PETAL_SHELL:-}"\n'
        'if [ -z "${_petal_shell}" ]; then\n'
        '  if [ -n "${ZSH_VERSION:-}" ]; then\n'
        "    _petal_shell=zsh\n"
        '  elif [ -n "${BASH_VERSION:-}" ]; then\n'
        "    _petal_shell=bash\n"
        "  else\n"
        # Not $SHELL: that is the login shell, not the one sourcing this.
        "    _petal_shell=sh\n"
        "  fi\n"
        "fi\n"
        "\n"
        'if [ -f "${_petal_ros_dir}/setup.${_petal_shell}" ]; then\n'
        '  . "${_petal_ros_dir}/setup.${_petal_shell}" || return $?\n'
        'elif [ -f "${_petal_ros_dir}/setup.sh" ]; then\n'
        '  . "${_petal_ros_dir}/setup.sh" || return $?\n'
        'elif [ -f "${_petal_ros_dir}/setup.bash" ]; then\n'
        '  . "${_petal_ros_dir}/setup.bash" || return $?\n'
        "else\n"
        '  echo "petal: no ROS setup file found in ${_petal_ros_dir}" >&2\n'
        "  return 1\n"
        "fi\n"
        "\n"
        "unset PYTHONHOME\n"
        '. "${_petal_ws}/.petal/venv/bin/activate" || return $?\n'
        # `PETAL_SHELL=x . script` keeps the assignment in POSIX shells.
        "unset _petal_ws _petal_ros_dir _petal_shell PETAL_SHELL\n",
        encoding="utf-8",
    )
    activate.chmod(0o755)
    return activate
