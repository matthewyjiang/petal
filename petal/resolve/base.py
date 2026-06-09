from __future__ import annotations

import itertools
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Protocol

from petal.identity import pip_name, python_apt_package
from petal.models import Dep, ResolvedDep


class Resolver(Protocol):
    def can_resolve(self, dep: Dep) -> bool: ...

    def resolve(self, dep: Dep) -> ResolvedDep | None: ...


class Runner(Protocol):
    def __call__(
        self, cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]: ...


class StreamRunner(Protocol):
    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]: ...


def default_runner(
    cmd: list[str], **kwargs: object
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            **kwargs,
        )
    except FileNotFoundError:
        # Return a failed result so callers handle it the same as a non-zero exit.
        return subprocess.CompletedProcess(
            cmd, returncode=127, stdout="", stderr=f"{cmd[0]}: command not found"
        )


def default_stream_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        if not sys.stderr.isatty():
            return subprocess.run(
                cmd,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

        done = threading.Event()

        def spin() -> None:
            for char in itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"):
                if done.is_set():
                    break
                print(f"\r  {char} working...", end="", file=sys.stderr, flush=True)
                time.sleep(0.08)

        thread = threading.Thread(target=spin, daemon=True)
        thread.start()
        try:
            return subprocess.run(
                cmd,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        finally:
            done.set()
            thread.join(timeout=0.2)
            print("\r", end="", file=sys.stderr, flush=True)
            print(" " * 24, end="", file=sys.stderr, flush=True)
            print("\r", end="", file=sys.stderr, flush=True)
    except FileNotFoundError:
        return subprocess.CompletedProcess(
            cmd, returncode=127, stdout="", stderr=f"{cmd[0]}: command not found"
        )


def canonical(name: str) -> str:
    return pip_name(name)


def python_apt_name(name: str) -> str:
    return python_apt_package(name)


def dep_requirement(dep: Dep) -> str:
    return f"{dep.name}{dep.version_spec}" if dep.version_spec else dep.name


def venv_python(venv: Path) -> Path:
    return venv / "bin" / "python"
