from __future__ import annotations

import itertools
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Protocol

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from petal.models import Dep


class Runner(Protocol):
    """Runs a command to completion, capturing text output; `input` feeds stdin."""

    def __call__(
        self, cmd: list[str], *, input: str | None = None
    ) -> subprocess.CompletedProcess[str]: ...


class StreamRunner(Protocol):
    def __call__(self, cmd: list[str]) -> subprocess.CompletedProcess[str]: ...


def default_runner(
    cmd: list[str], *, input: str | None = None
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd, check=False, text=True, capture_output=True, input=input
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
                capture_output=True,
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
                capture_output=True,
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


def dep_requirement(dep: Dep) -> str:
    return f"{dep.name}{dep.version_spec}" if dep.version_spec else dep.name


def venv_python(venv: Path) -> Path:
    return venv / "bin" / "python"


def satisfies(version: str, spec: str) -> bool:
    """True when `version` meets `spec`; an empty spec accepts anything."""
    if not spec:
        return True
    try:
        return SpecifierSet(spec).contains(version, prereleases=True)
    except (InvalidSpecifier, InvalidVersion):
        return False


def upstream_version(debian_version: str) -> str:
    """PEP 440 form of a Debian version, or "" when it has none.

    `1:1.24.2-1ubuntu1` -> `1.24.2`; `2.25.1+dfsg-2` -> `2.25.1+dfsg`;
    `1.8.0~rc1-1` -> `1.8.0rc1` (Debian marks pre-releases with `~`).
    """
    version = debian_version.split(":", 1)[-1].rsplit("-", 1)[0].replace("~", "")
    try:
        return str(Version(version))
    except InvalidVersion:
        return ""
