"""The ROS/system Python packages a petal venv sees through system site-packages.

Pip must not replace these: ROS packages are built against the system copies, and
uv ignores system site-packages when installing, so without guidance it happily
installs shadowing copies into `.petal/venv`. Petal pins every system
distribution in a constraints file and never installs what the system provides.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from packaging.version import InvalidVersion, Version

from petal import env
from petal.identity import pip_name

_INSPECT = """
import importlib.metadata, json, pkgutil, re
dists = {}
for dist in importlib.metadata.distributions():
    name = dist.metadata["Name"]
    if name:
        dists.setdefault(re.sub(r"[-_.]+", "-", name).lower(), dist.version)
mods = sorted({m.name for m in pkgutil.iter_modules()})
print(json.dumps({"distributions": dists, "modules": mods}))
"""


@dataclass(frozen=True)
class SystemPython:
    """Snapshot of what the ROS interpreter imports outside `.petal/venv`."""

    # Canonical (PEP 503) name -> PEP 440 version, first on sys.path wins.
    distributions: dict[str, str] = field(default_factory=dict)
    # Top-level importable module names, for ROS packages without metadata.
    modules: frozenset[str] = frozenset()


def inspect_system_python(distro: str) -> SystemPython:
    """Inspect the ROS distro's interpreter as an activated petal venv sees it.

    `-s` drops user site-packages (venvs ignore them) and PYTHONPATH is exactly
    the ROS directories that `.petal/activate` adds, so the result does not
    depend on what the caller's shell happens to have sourced.
    """
    interpreter = env.distro_python(distro)
    lib = env.ros_root() / distro
    paths = [
        *sorted((lib / "lib").glob("python3.*/site-packages")),
        *sorted((lib / "local" / "lib").glob("python3.*/dist-packages")),
    ]
    child_env = {**os.environ, "PYTHONPATH": os.pathsep.join(map(str, paths))}
    proc = subprocess.run(
        [str(interpreter), "-s", "-c", _INSPECT],
        check=True,
        text=True,
        capture_output=True,
        env=child_env,
    )
    return parse_inspection(proc.stdout)


def parse_inspection(output: str) -> SystemPython:
    data = json.loads(output)
    distributions: dict[str, str] = {}
    for name, version in data["distributions"].items():
        try:
            Version(version)
        except InvalidVersion:
            # Cannot pin or compare it; leave it to import-name detection.
            continue
        distributions[pip_name(name)] = version
    return SystemPython(distributions, frozenset(data["modules"]))


class SystemView:
    """System packages plus the constraints file that keeps pip off them.

    Inspection is lazy and thread-safe: a sync that installs nothing never
    starts the ROS interpreter. `allow_shadow` names packages the user
    explicitly asked pip to install (`{ pip = ... }` in petal.toml); those are
    left unpinned and may shadow the system copy.
    """

    def __init__(
        self,
        load: Callable[[], SystemPython],
        *,
        constraints_path: Path | None,
        allow_shadow: Iterable[str] = (),
    ) -> None:
        self._load = load
        self._constraints_path = constraints_path
        self._python: SystemPython | None = None
        self._lock = threading.Lock()
        self.allow_shadow = frozenset(pip_name(name) for name in allow_shadow)

    @property
    def python(self) -> SystemPython:
        with self._lock:
            if self._python is None:
                self._python = self._load()
                self._write_constraints(self._python)
            return self._python

    def refresh(self) -> None:
        """Forget the snapshot, e.g. after apt installed python3-* packages."""
        with self._lock:
            self._python = None

    def constraints_file(self) -> Path | None:
        """Path of the up-to-date constraints file, or None without a ROS view."""
        _ = self.python
        return self._constraints_path

    def version(self, name: str) -> str:
        """System version of a distribution, or "" when the system lacks it."""
        return self.python.distributions.get(pip_name(name), "")

    def provides(self, name: str, version: str) -> bool:
        return bool(version) and self.version(name) == version

    def protects(self, name: str) -> bool:
        """True when pip must leave this system distribution alone."""
        key = pip_name(name)
        return key in self.python.distributions and key not in self.allow_shadow

    def _write_constraints(self, python: SystemPython) -> None:
        if self._constraints_path is None:
            return
        self._constraints_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Generated by petal: ROS/system Python packages pip must not replace.",
            *(
                f"{name}=={version}"
                for name, version in sorted(python.distributions.items())
                if name not in self.allow_shadow
            ),
        ]
        self._constraints_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# No system packages and no constraints file; for callers without a ROS view.
NO_SYSTEM = SystemView(SystemPython, constraints_path=None)
