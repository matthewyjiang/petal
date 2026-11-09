"""Enter the canonical workspace environment without changing the caller's shell."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from petal.env import PetalEnvError


def _activation(workspace: Path) -> Path:
    script = workspace / ".petal/activate"
    if not script.is_file():
        raise PetalEnvError(f"{script} not found; run `petal init` first")
    if not (workspace / ".petal/venv/bin/python").is_file():
        raise PetalEnvError(
            "Workspace venv is missing; run `petal sync` to recreate it"
        )
    return script


def _shell_executable(shell: str) -> str:
    executable = shutil.which(shell)
    if executable is None:
        raise PetalEnvError(
            f"Shell {shell!r} not found; install it or choose another shell"
        )
    return executable


def run_command(workspace: Path, argv: list[str]) -> int:
    """Replace Petal with a command after sourcing ROS and the workspace venv."""
    script = _activation(workspace)
    bash = _shell_executable("bash")
    child_env = dict(os.environ)
    # Noninteractive bash reads BASH_ENV even with --norc. Only the bootstrap
    # suppresses it; an explicitly launched shell retains the caller's setting.
    bash_env = child_env.pop("BASH_ENV", None)
    restore = (
        f"export BASH_ENV={shlex.quote(bash_env)}\n" if bash_env is not None else ""
    )
    bootstrap = (
        restore + 'PETAL_SHELL=bash . "$1" || exit $?\n' + 'shift\nexec -- "$@"\n'
    )
    try:
        os.execve(
            bash,
            [
                bash,
                "--noprofile",
                "--norc",
                "-c",
                bootstrap,
                "petal run",
                str(script),
                *argv,
            ],
            child_env,
        )
    except OSError as exc:
        raise PetalEnvError(f"Could not start command: {exc}") from exc


def _startup_tail(script: Path, shell: str) -> str:
    return (
        f"PETAL_SHELL={shell} . {shlex.quote(str(script))} || exit $?\n"
        "printf 'Petal environment: %s · ROS %s\\nType exit to leave.\\n' "
        '"${VIRTUAL_ENV}" "${ROS_DISTRO:-unknown}" >&2\n'
    )


def _write_startup(directory: Path, script: Path, shell: str) -> list[str]:
    """Build private startup files, leaving the user's dotfiles untouched."""
    tail = _startup_tail(script, shell)
    if shell == "bash":
        rc = directory / "bashrc"
        rc.write_text(
            'if [ -f "$HOME/.bashrc" ]; then . "$HOME/.bashrc"; fi\n' + tail,
            encoding="utf-8",
        )
        return ["--rcfile", str(rc), "-i"]

    # zsh has no --rcfile. Interpose a private ZDOTDIR, but let the real .zshenv
    # select the user's dotfile directory before forwarding to their .zshrc.
    restore = (
        f"export ZDOTDIR={shlex.quote(os.environ['ZDOTDIR'])}\n"
        if "ZDOTDIR" in os.environ
        else "unset ZDOTDIR\n"
    )
    (directory / ".zshenv").write_text(
        restore
        + 'if [[ -f "${ZDOTDIR-$HOME}/.zshenv" ]]; then\n'
        + '  . "${ZDOTDIR-$HOME}/.zshenv"\nfi\n'
        + "if [[ ! -o rcs ]]; then\n"
        + '  print -u2 "petal: petal shell requires zsh startup files (setopt RCS)"\n'
        + "  exit 1\nfi\n"
        + "_petal_zdotdir_set=${ZDOTDIR+x}\n_petal_zdotdir=${ZDOTDIR-}\n"
        + f"ZDOTDIR={shlex.quote(str(directory))}\n",
        encoding="utf-8",
    )
    (directory / ".zshrc").write_text(
        "if [[ -n $_petal_zdotdir_set ]]; then\n"
        "  ZDOTDIR=$_petal_zdotdir\nelse\n  unset ZDOTDIR\nfi\n"
        "unset _petal_zdotdir_set _petal_zdotdir\n"
        'if [[ -f "${ZDOTDIR-$HOME}/.zshrc" ]]; then\n'
        '  . "${ZDOTDIR-$HOME}/.zshrc"\nfi\n' + tail,
        encoding="utf-8",
    )
    return ["-i"]


def open_shell(workspace: Path, requested_shell: str | None) -> int:
    """Run an interactive shell; retain a parent only to clean up startup files."""
    script = _activation(workspace)
    requested = requested_shell or os.environ.get("SHELL") or "/bin/bash"
    shell = Path(requested).name
    if shell not in {"bash", "zsh"}:
        raise PetalEnvError(
            f"Unsupported shell {requested!r}; use `petal shell --shell bash` or `--shell zsh`"
        )
    executable = _shell_executable(requested)
    try:
        with TemporaryDirectory(prefix="petal-shell-") as temporary:
            directory = Path(temporary)
            args = _write_startup(directory, script, shell)
            child_env = dict(os.environ)
            if shell == "zsh":
                child_env["ZDOTDIR"] = str(directory)
            with subprocess.Popen([executable, *args], env=child_env) as child:
                # The shell owns Ctrl-C/Ctrl-\ handling. Ignoring these only AFTER
                # spawning keeps the shell's own signal dispositions intact.
                previous = {
                    sig: signal.signal(sig, signal.SIG_IGN)
                    for sig in (signal.SIGINT, signal.SIGQUIT)
                }
                try:
                    status = child.wait()
                finally:
                    for sig, handler in previous.items():
                        signal.signal(sig, handler)
            return status if status >= 0 else 128 - status
    except OSError as exc:
        raise PetalEnvError(f"Could not start shell: {exc}") from exc
