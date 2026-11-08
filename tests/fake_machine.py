"""A scripted machine for CLI tests: rosdep, apt, a tiny PyPI and the venv.

`FakeMachine.host()` plugs into `petal.cli.main(argv, host=...)`, so tests run
the real resolver, planner and installer and assert what a user would see:
files, installed packages, output and exit codes.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from petal.host import Host
from petal.preflight import PreflightReport
from petal.system import SystemPython


@dataclass
class Deb:
    version: str  # Debian version, e.g. "1:1.24.2-1ubuntu1"
    provides: dict[str, str] = field(default_factory=dict)  # dist -> version


@dataclass
class FakeMachine:
    # ROS/system Python distributions (canonical name -> version) and modules.
    system: dict[str, str] = field(default_factory=dict)
    modules: set[str] = field(default_factory=set)
    # rosdep key -> ("apt", deb) or ("pip", pypi name)
    rosdep: dict[str, tuple[str, str]] = field(default_factory=dict)
    apt: dict[str, Deb] = field(default_factory=dict)
    apt_installed: set[str] = field(default_factory=set)
    # PyPI: name -> (latest version, dependency names); any exact pin exists.
    pypi: dict[str, tuple[str, list[str]]] = field(default_factory=dict)
    venv: dict[str, str] = field(default_factory=dict)
    uninstall_fails: bool = False
    commands: list[list[str]] = field(default_factory=list)

    def host(self) -> Host:
        return Host(
            runner=self.run,
            install_runner=lambda cmd: self.run(cmd),
            check_tools=PreflightReport,
            detect_ros_distro=lambda: "humble",
            ensure_venv=self._ensure_venv,
            inspect_system=lambda distro: SystemPython(
                dict(self.system), frozenset(self.modules)
            ),
        )

    def ran(self, *prefix: str) -> list[list[str]]:
        return [cmd for cmd in self.commands if cmd[: len(prefix)] == list(prefix)]

    def run(
        self, cmd: list[str], *, input: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(cmd)
        match cmd:
            case ["rosdep", "resolve", key, *_]:
                if key not in self.rosdep:
                    return _done(cmd, 1, err=f"no rosdep rule for {key}")
                installer, value = self.rosdep[key]
                return _done(cmd, out=f"#{installer}\n{value}\n")
            case ["apt-cache", "policy", pkg]:
                deb = self.apt.get(pkg)
                return _done(
                    cmd, out=f"  Candidate: {deb.version if deb else '(none)'}\n"
                )
            case ["dpkg-query", "-W", fmt, pkg]:
                if pkg not in self.apt_installed:
                    return _done(cmd, 1)
                status = (
                    "install ok installed" if "Status" in fmt else self.apt[pkg].version
                )
                return _done(cmd, out=status)
            case ["sudo", "apt-get", "install", "-y", *pkgs]:
                for pkg in pkgs:
                    self.apt_installed.add(pkg)
                    self.system.update(self.apt[pkg].provides)
                return _done(cmd)
            case ["uv", "pip", "compile", *args]:
                return self._compile(cmd, args, input or "")
            case ["uv", "pip", "list", *_]:
                rows = [{"name": n, "version": v} for n, v in self.venv.items()]
                return _done(cmd, out=json.dumps(rows))
            case ["uv", "pip", "install", *args]:
                for req in (a for a in args if "==" in a):
                    name, version = req.split("==", 1)
                    self.venv[canonicalize_name(name)] = version
                return _done(cmd)
            case ["uv", "pip", "uninstall", *args]:
                if self.uninstall_fails:
                    return _done(cmd, 1, err="uninstall failed")
                self.venv.pop(canonicalize_name(args[-1]), None)
                return _done(cmd)
            case [_, "-c", code] if code.startswith("import "):
                module = code.removeprefix("import ")
                return _done(cmd, 0 if module in self.modules else 1)
        raise AssertionError(f"unexpected command: {cmd}")

    def _compile(
        self, cmd: list[str], args: list[str], stdin: str
    ) -> subprocess.CompletedProcess[str]:
        pinned = {}
        if "--constraints" in args:
            text = Path(args[args.index("--constraints") + 1]).read_text()
            for line in text.splitlines():
                if "==" in line and not line.startswith("#"):
                    name, version = line.split("==", 1)
                    pinned[name] = version
        # Like uv: an existing output file holds soft version preferences.
        output = Path(args[args.index("--output-file") + 1])
        preferred = dict(
            line.split("==", 1) for line in output.read_text().splitlines() if line
        )
        pins: dict[str, str] = {}
        queue = [Requirement(line) for line in stdin.splitlines() if line.strip()]
        while queue:
            req = queue.pop()
            name = canonicalize_name(req.name)
            if name in pinned:
                version = pinned[name]
            elif name in preferred and req.specifier.contains(preferred[name]):
                version = preferred[name]
                queue.extend(Requirement(dep) for dep in self.pypi[name][1])
            elif name in self.pypi:
                # Older releases exist too: an exact pin picks that version.
                exact = [sp.version for sp in req.specifier if sp.operator == "=="]
                version = exact[0] if exact else self.pypi[name][0]
                queue.extend(Requirement(dep) for dep in self.pypi[name][1])
            else:
                return _done(
                    cmd, 1, err=f"{name} was not found in the package registry"
                )
            if not req.specifier.contains(version, prereleases=True):
                return _done(cmd, 1, err=f"{name}{req.specifier} is unsatisfiable")
            pins[name] = version
        output.write_text("".join(f"{n}=={v}\n" for n, v in sorted(pins.items())))
        return _done(cmd)

    def _ensure_venv(self, workspace: Path, distro: str) -> Path:
        venv = workspace / ".petal" / "venv"
        venv.mkdir(parents=True, exist_ok=True)
        return venv


def _done(
    cmd: list[str], code: int = 0, *, out: str = "", err: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, code, stdout=out, stderr=err)


def workspace(
    root: Path,
    *,
    deps: str = "",
    overrides: str = "",
    packages: dict[str, tuple[list[str], list[str]]] | None = None,
) -> Path:
    """A ROS workspace: petal.toml plus `packages` name -> (package.xml keys,
    setup.cfg install_requires)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "petal.toml").write_text(
        f'[workspace]\nros_distro = "humble"\n\n[deps]\n{deps}\n[overrides]\n{overrides}',
        encoding="utf-8",
    )
    for name, (keys, requires) in (packages or {}).items():
        pkg = root / "src" / name
        pkg.mkdir(parents=True)
        depends = "".join(f"<exec_depend>{key}</exec_depend>" for key in keys)
        (pkg / "package.xml").write_text(
            f'<package format="3"><name>{name}</name>{depends}</package>',
            encoding="utf-8",
        )
        if requires:
            lines = "".join(f"\n    {req}" for req in requires)
            (pkg / "setup.cfg").write_text(
                f"[options]\ninstall_requires ={lines}\n", encoding="utf-8"
            )
    return root
