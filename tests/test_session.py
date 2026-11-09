"""Exercise the CLI with real shells, a local venv, and fake ROS setup."""

from __future__ import annotations

import json
import os
import pty
import select
import shutil
import signal
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from petal import env


@pytest.fixture
def session_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "robot's workspace"
    ws.mkdir()
    (ws / "petal.toml").write_text('[workspace]\nros_distro = "humble"\n')
    venv.EnvBuilder(system_site_packages=True, with_pip=False, symlinks=True).create(
        ws / ".petal/venv"
    )
    ros = tmp_path / "ros/humble"
    ros.mkdir(parents=True)
    (ros / "ros_probe.py").write_text('VALUE = "from ROS"\n')
    for shell in ("bash", "zsh", "sh"):
        (ros / f"setup.{shell}").write_text(
            f'export ROS_DISTRO=humble\nexport PYTHONPATH="{ros}"\n'
        )
    monkeypatch.setenv("PETAL_ROS_ROOT", str(ros.parent))
    env.write_activate(ws, "humble")
    home = tmp_path / "home"
    home.mkdir()
    for shell in ("bash", "zsh"):
        (home / f".{shell}rc").write_text(
            "export PATH=/usr/bin:/bin\nexport STARTUP_LOADED=yes\n"
        )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("SHELL", "/bin/bash")
    monkeypatch.delenv("ZDOTDIR", raising=False)
    monkeypatch.delenv("BASH_ENV", raising=False)
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("PETAL_SHELL", raising=False)
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).resolve().parents[1]))
    return ws


def petal(
    ws: Path, *args: str, input: str | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "petal.cli", *args],
        cwd=ws,
        input=input,
        text=True,
        capture_output=True,
        check=False,
    )


def test_run_activates_ros_and_venv_preserving_cwd_and_arguments(
    session_workspace: Path,
) -> None:
    ws = session_workspace
    child = ws / "src/package"
    child.mkdir(parents=True)
    args = [
        "two words",
        "$(touch SHOULD_NOT_EXIST)",
        "'quoted'",
        "--workspace",
        "other",
    ]
    result = petal(
        child,
        "run",
        "python",
        "-c",
        "import json, os, sys, ros_probe; "
        "print(json.dumps([sys.prefix, os.getcwd(), os.environ['ROS_DISTRO'], "
        "ros_probe.VALUE, sys.argv[1:]]))",
        *args,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        str(ws / ".petal/venv"),
        str(child),
        "humble",
        "from ROS",
        args,
    ]
    assert not (child / "SHOULD_NOT_EXIST").exists()


@pytest.mark.parametrize(
    "command", [["bash", "-c", "exit 23"], ["--", "bash", "-c", "exit 23"]]
)
def test_run_preserves_exit_status(session_workspace: Path, command: list[str]) -> None:
    assert petal(session_workspace, "run", *command).returncode == 23


def test_run_accepts_explicit_workspace_from_elsewhere(session_workspace: Path) -> None:
    result = petal(
        Path.cwd(),
        "run",
        "--workspace",
        str(session_workspace),
        "python",
        "-c",
        "import sys; print(sys.prefix)",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(session_workspace / ".petal/venv")


def test_run_preserves_signal_delivery(session_workspace: Path) -> None:
    result = petal(session_workspace, "run", "bash", "-c", "kill -TERM $$")
    assert result.returncode == -signal.SIGTERM


def test_run_does_not_read_bash_env(
    session_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    startup = session_workspace / "unexpected-startup"
    startup.write_text("exit 99\n")
    monkeypatch.setenv("BASH_ENV", str(startup))
    result = petal(session_workspace, "run", "/bin/echo", "child")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "child\n"


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_shell_activates_after_startup(session_workspace: Path, shell: str) -> None:
    if not shutil.which(shell):
        pytest.skip(f"{shell} is not installed")
    result = petal(
        session_workspace,
        "shell",
        "--shell",
        shell,
        input="python -c 'import os, sys, ros_probe; print(sys.prefix); "
        'print(os.environ["STARTUP_LOADED"]); print(ros_probe.VALUE)\'\nexit 17\n',
    )
    assert result.returncode == 17, result.stderr
    assert str(session_workspace / ".petal/venv") in result.stdout
    assert "yes\nfrom ROS\n" in result.stdout
    assert "Type exit to leave." in result.stderr


def test_zsh_preserves_zdotdir_and_reads_zshenv(
    session_workspace: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    if not shutil.which("zsh"):
        pytest.skip("zsh is not installed")
    dotdir = tmp_path / "custom dotfiles"
    dotdir.mkdir()
    (dotdir / ".zshenv").write_text("export ENV_LOADED=yes\n")
    (dotdir / ".zshrc").write_text("export PATH=/usr/bin:/bin\n")
    monkeypatch.setenv("ZDOTDIR", str(dotdir))
    result = petal(
        session_workspace,
        "shell",
        "--shell",
        "zsh",
        input='printf "RESULT:%s:%s\\n" "$ENV_LOADED" "$ZDOTDIR"\n'
        "python -c 'import ros_probe; print(ros_probe.VALUE)'\nexit\n",
    )
    assert result.returncode == 0, result.stderr
    assert f"RESULT:yes:{dotdir}" in result.stdout
    assert "from ROS" in result.stdout


@pytest.mark.parametrize("command", ["run", "shell"])
def test_session_requires_existing_environment(tmp_path: Path, command: str) -> None:
    args = [command, "--workspace", str(tmp_path)]
    if command == "run":
        args.extend(["/bin/echo", "should not run"])
    result = petal(Path.cwd(), *args)
    assert result.returncode == 1
    assert "petal init" in result.stderr
    assert "should not run" not in result.stdout
    assert not (tmp_path / ".petal").exists()


def test_run_requires_command(session_workspace: Path) -> None:
    result = petal(session_workspace, "run")
    assert result.returncode == 2
    assert "command" in result.stderr


def test_shell_rejects_unsupported_shell(session_workspace: Path) -> None:
    result = petal(session_workspace, "shell", "--shell", "fish")
    assert result.returncode != 0
    assert "bash" in result.stderr and "zsh" in result.stderr


def test_run_does_not_interpret_executable_as_an_exec_option(
    session_workspace: Path,
) -> None:
    command = session_workspace / ".petal/venv/bin/-petal-probe"
    command.write_text("#!/bin/sh\nprintf 'command ran\\n'\n")
    command.chmod(0o755)
    result = petal(session_workspace, "run", "--", "-petal-probe")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "command ran\n"


def test_run_reports_missing_command(session_workspace: Path) -> None:
    result = petal(session_workspace, "run", "petal-nonexistent-command")
    assert result.returncode == 127
    assert "petal-nonexistent-command" in result.stderr


@pytest.mark.parametrize("command", ["run", "shell"])
def test_failed_activation_never_launches_command_or_prompt(
    session_workspace: Path, command: str
) -> None:
    (session_workspace / ".petal/venv/bin/activate").write_text("return 29\n")
    args = [command]
    if command == "run":
        args += ["/bin/echo", "SHOULD_NOT_RUN"]
    result = petal(session_workspace, *args, input="echo SHOULD_NOT_RUN\nexit\n")
    assert result.returncode == 29, result.stderr
    assert "SHOULD_NOT_RUN" not in result.stdout


def test_shell_defaults_to_bash_when_shell_is_unset(
    session_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SHELL", raising=False)
    result = petal(
        session_workspace,
        "shell",
        input='test -n "$BASH_VERSION" || exit 1\nprintf "bash selected\\n"\nexit\n',
    )
    assert result.returncode == 0, result.stderr
    assert "bash selected" in result.stdout


def test_missing_venv_suggests_sync(session_workspace: Path) -> None:
    (session_workspace / ".petal/venv/bin/python").unlink()
    result = petal(session_workspace, "run", "/bin/echo", "SHOULD_NOT_RUN")
    assert result.returncode == 1
    assert "petal sync" in result.stderr
    assert "SHOULD_NOT_RUN" not in result.stdout


def test_zsh_with_disabled_startup_files_fails_instead_of_opening_unactivated_shell(
    session_workspace: Path,
) -> None:
    if not shutil.which("zsh"):
        pytest.skip("zsh is not installed")
    (Path(os.environ["HOME"]) / ".zshenv").write_text("unsetopt RCS\n")
    result = petal(
        session_workspace, "shell", "--shell", "zsh", input="echo WRONG\nexit\n"
    )
    assert result.returncode == 1
    assert "RCS" in result.stderr
    assert "WRONG" not in result.stdout


def test_shell_uses_shell_preference_and_preserves_cwd(
    session_workspace: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    if not shutil.which("zsh"):
        pytest.skip("zsh is not installed")
    monkeypatch.setenv("SHELL", shutil.which("zsh") or "zsh")
    child = session_workspace / "src"
    child.mkdir()
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    monkeypatch.setenv("TMPDIR", str(temporary))
    result = petal(
        child,
        "shell",
        input='test -n "$ZSH_VERSION" || exit 1\nprintf "zsh selected\\n"\npwd\nexit\n',
    )
    assert result.returncode == 0, result.stderr
    assert "zsh selected" in result.stdout and str(child) in result.stdout
    assert not list(temporary.iterdir())


def test_zshenv_can_redirect_startup_files(
    session_workspace: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    if not shutil.which("zsh"):
        pytest.skip("zsh is not installed")
    redirected = tmp_path / "redirected"
    redirected.mkdir()
    home = Path(os.environ["HOME"])
    (home / ".zshenv").write_text(f'ZDOTDIR="{redirected}"\n')
    (redirected / ".zshrc").write_text("export STARTUP_LOADED=redirected\n")
    result = petal(
        session_workspace,
        "shell",
        "--shell",
        "zsh",
        input='printf "RESULT:%s:%s\\n" "$STARTUP_LOADED" "$ZDOTDIR"\nexit\n',
    )
    assert result.returncode == 0, result.stderr
    assert f"RESULT:redirected:{redirected}" in result.stdout


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_shell_ctrl_c_and_exit_in_terminal(session_workspace: Path, shell: str) -> None:
    if not shutil.which(shell):
        pytest.skip(f"{shell} is not installed")
    pid, terminal = pty.fork()
    if pid == 0:
        os.chdir(session_workspace)
        os.execv(
            sys.executable,
            [sys.executable, "-m", "petal.cli", "shell", "--shell", shell],
        )

    def read_until(marker: bytes) -> None:
        output = b""
        while marker not in output:
            # The complete initial shell suite took 1.51s locally. This generous
            # stall watchdog accommodates slower CI; it is not a performance cap.
            readable, _, _ = select.select([terminal], [], [], 30)
            assert readable, f"Shell stalled waiting for {marker!r}: {output!r}"
            chunk = os.read(terminal, 4096)
            assert chunk, f"Shell exited before {marker!r}: {output!r}"
            output += chunk

    try:
        read_until(b"Type exit to leave.")
        # Wait until a foreground command has actually started, then send the
        # terminal's real Ctrl-C byte. The session must return to a usable prompt.
        os.write(
            terminal,
            b'python -c \'import signal; print("PETAL_" + "READY", flush=True); signal.pause()\'\n',
        )
        read_until(b"PETAL_READY")
        os.write(terminal, b"\x03")
        os.write(terminal, b"printf 'PETAL_%s\\n' ALIVE\n")
        read_until(b"PETAL_ALIVE")
        # A signal delivered to the waiting Petal parent must not kill the shell.
        os.write(terminal, b"kill -INT $PPID; printf 'PETAL_%s\\n' PARENT_ALIVE\n")
        read_until(b"PETAL_PARENT_ALIVE")
        os.write(terminal, b"exit 19\n")
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 19
    finally:
        os.close(terminal)
        # Closing the controlling terminal also stops a shell on assertion failure.
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
