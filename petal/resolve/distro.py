from __future__ import annotations

from petal import env
from petal.models import Dep, ResolvedDep, Source
from petal.resolve.base import canonical


KNOWN_IMPORTS = {
    "opencv-python": "cv2",
    "pyyaml": "yaml",
    "ml-collections": "ml_collections",
}


class DistroResolver:
    def __init__(self, distro: str, modules: set[str] | None = None) -> None:
        self.distro = distro
        self.modules = modules

    def _modules(self) -> set[str]:
        if self.modules is None:
            self.modules = env.distro_provided_modules(self.distro)
        return self.modules

    def can_resolve(self, dep: Dep) -> bool:
        return self._import_name(dep.name) in self._modules()

    def resolve(self, dep: Dep) -> ResolvedDep | None:
        if not self.can_resolve(dep):
            return None
        return ResolvedDep(dep=dep, chosen_source=Source.DISTRO)

    @staticmethod
    def _import_name(name: str) -> str:
        value = canonical(name)
        return KNOWN_IMPORTS.get(value, value.replace("-", "_"))
