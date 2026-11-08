"""The ROS/system Python packages a petal venv sees through system site-packages.

Pip must not replace these: ROS packages are built against the system copies, and
uv ignores system site-packages when installing, so without guidance it happily
installs shadowing copies into `.petal/venv`. Petal pins every system
distribution in a constraints file and never installs what the system provides.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from packaging.version import InvalidVersion, Version

from petal import env
from petal.identity import pip_name

# Run with `-I` (no cwd, user site or PYTHON* variables) so the result does not
# depend on where petal runs or what the caller's shell has sourced; the ROS
# directories arrive as argv and are put first on sys.path, as activation does.
_INSPECT = """
import importlib.metadata, json, pkgutil, re, sys
sys.path[:0] = sys.argv[1:]
dists = {}
for dist in importlib.metadata.distributions():
    name = dist.metadata["Name"]
    if name:
        dists.setdefault(re.sub(r"[-_.]+", "-", name).lower(), dist.version)
mods = sorted({m.name for m in pkgutil.iter_modules()})
print(json.dumps({"distributions": dists, "modules": mods}))
"""

# Installed into every venv by `python -m venv`; not shadowing anything ROS uses.
_VENV_SEED = frozenset({"pip", "setuptools", "wheel"})


@dataclass(frozen=True)
class SystemPython:
    """Snapshot of what the ROS interpreter imports outside `.petal/venv`."""

    # Canonical (PEP 503) name -> PEP 440 version, first on sys.path wins.
    distributions: dict[str, str] = field(default_factory=dict)
    # Top-level importable module names, for ROS packages without metadata.
    modules: frozenset[str] = frozenset()


def inspect_system_python(distro: str) -> SystemPython:
    """Inspect the ROS distro's interpreter as an activated petal venv sees it."""
    interpreter = env.distro_python(distro)
    ros = env.ros_root() / distro
    paths = [
        *sorted((ros / "lib").glob("python3.*/site-packages")),
        *sorted((ros / "local" / "lib").glob("python3.*/dist-packages")),
    ]
    cmd = [str(interpreter), "-I", "-c", _INSPECT, *map(str, paths)]
    try:
        proc = subprocess.run(cmd, check=True, text=True, capture_output=True)
        return parse_inspection(proc.stdout)
    except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        raise env.PetalEnvError(
            f"could not inspect ROS Python packages with {interpreter}: {detail}"
        ) from exc


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

    `allow_shadow` names packages declared explicitly as pip deps in the
    manifest's `[deps]`; those are left unpinned and may shadow the system copy.
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
        self.allow_shadow = frozenset(pip_name(name) for name in allow_shadow)
        self.python = load()
        self._write_constraints()

    def refresh(self) -> bool:
        """Re-inspect, e.g. after apt installed python3-* packages; True if changed."""
        before = self.python
        self.python = self._load()
        if self.python == before:
            return False
        self._write_constraints()
        return True

    def constraint_args(self) -> list[str]:
        """uv arguments that pin every protected system distribution."""
        if self._constraints_path is None:
            return []
        return ["--constraints", str(self._constraints_path)]

    def version(self, name: str) -> str:
        """System version of a distribution, or "" when the system lacks it."""
        return self.python.distributions.get(pip_name(name), "")

    def protects(self, name: str) -> bool:
        """True when pip must leave this system distribution alone."""
        key = pip_name(name)
        return key in self.python.distributions and key not in self.allow_shadow

    def shadowed_by(self, installed: dict[str, str]) -> dict[str, str]:
        """Venv packages (name -> version) that shadow a protected system copy."""
        return {
            name: version
            for name, version in installed.items()
            if name not in _VENV_SEED and self.protects(name)
        }

    def _write_constraints(self) -> None:
        if self._constraints_path is None:
            return
        self._constraints_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "# Generated by petal: ROS/system Python packages pip must not replace.",
            *(
                f"{name}=={version}"
                for name, version in sorted(self.python.distributions.items())
                if name not in self.allow_shadow
            ),
        ]
        self._constraints_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# No system packages and no constraints file; for tests and callers without ROS.
NO_SYSTEM = SystemView(SystemPython, constraints_path=None)
