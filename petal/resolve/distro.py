from __future__ import annotations

from petal.identity import pip_name
from petal.models import Dep, ResolvedDep, Source
from petal.resolve.base import satisfies
from petal.system import SystemView

KNOWN_IMPORTS = {
    "opencv-python": "cv2",
    "pyyaml": "yaml",
    "ml-collections": "ml_collections",
}


class DistroResolver:
    """Resolves deps the ROS/system Python already provides; installs nothing."""

    def __init__(self, system: SystemView) -> None:
        self.system = system

    def resolve(self, dep: Dep) -> ResolvedDep | None:
        version = self.system.version(dep.name)
        if version:
            if not satisfies(version, dep.version_spec):
                return None
            return ResolvedDep(dep, Source.DISTRO, resolved_version=version)
        # Python requirements are distribution names: without matching metadata
        # the system does not provide them, whatever happens to be importable.
        if dep.source_hint == Source.PIP:
            return None
        # ROS packages such as rclpy often ship without distribution metadata.
        if self._import_name(dep.name) in self.system.python.modules:
            return ResolvedDep(dep, Source.DISTRO)
        return None

    @staticmethod
    def _import_name(name: str) -> str:
        value = pip_name(name)
        return KNOWN_IMPORTS.get(value, value.replace("-", "_"))
