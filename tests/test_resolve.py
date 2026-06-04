from __future__ import annotations

import subprocess
from pathlib import Path

from petal.models import Dep, Source
from petal.resolve.apt import AptResolver, _candidate_version
from petal.resolve.base import canonical, python_apt_name
from petal.resolve.distro import DistroResolver
from petal.resolve.manager import ResolutionManager
from petal.resolve.pip import PipResolver, parse_pip_version
from petal.resolve.rosdep import RosdepResolver, parse_rosdep_resolve


FIXTURES = Path(__file__).parent / "fixtures" / "cmd_output"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def completed(cmd: list[str], stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")


def test_canonical_helpers() -> None:
    assert canonical("ml_collections") == "ml-collections"
    assert canonical("Foo_Bar") == "foo-bar"
    assert python_apt_name("NumPy") == "python3-numpy"
    assert python_apt_name("python3-numpy") == "python3-numpy"


def test_distro_resolver_short_circuits_rclpy() -> None:
    resolver = DistroResolver("humble", modules={"rclpy", "launch"})
    dep = Dep("rclpy", source_hint=Source.ROSDEP, origin_packages=["pkg_a"])
    resolved = resolver.resolve(dep)
    assert resolved is not None
    assert resolved.chosen_source == Source.DISTRO
    assert resolved.dep is dep


def test_parse_rosdep_apt_output() -> None:
    parsed = parse_rosdep_resolve(fixture("rosdep_apt_numpy.txt"))
    assert parsed.apt == ["python3-numpy"]
    assert parsed.pip == []


def test_parse_rosdep_pip_output() -> None:
    parsed = parse_rosdep_resolve(fixture("rosdep_pip_ml_collections.txt"))
    assert parsed.apt == []
    assert parsed.pip == ["ml-collections"]


def test_rosdep_resolver_maps_apt() -> None:
    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd[:3] == ["rosdep", "resolve", "numpy"]
        return completed(cmd, fixture("rosdep_apt_numpy.txt"))

    resolved = RosdepResolver("humble", runner).resolve(Dep("numpy", source_hint=Source.ROSDEP))
    assert resolved is not None
    assert resolved.chosen_source == Source.APT
    assert resolved.apt_pkg == "python3-numpy"


def test_rosdep_resolver_maps_pip() -> None:
    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return completed(cmd, fixture("rosdep_pip_ml_collections.txt"))

    dep = Dep("ml_collections", source_hint=Source.ROSDEP, origin_packages=["pkg_b"])
    resolved = RosdepResolver("humble", runner).resolve(dep)
    assert resolved is not None
    assert resolved.chosen_source == Source.PIP
    assert resolved.dep.name == "ml-collections"
    assert resolved.dep.origin_packages == ["pkg_b"]


def test_apt_resolver_candidate_version() -> None:
    assert _candidate_version(fixture("apt_policy_numpy.txt")) == "1:1.24.2-1ubuntu1"
    assert _candidate_version(fixture("apt_policy_missing.txt")) == ""


def test_apt_resolver_maps_python_package() -> None:
    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd == ["apt-cache", "policy", "python3-numpy"]
        return completed(cmd, fixture("apt_policy_numpy.txt"))

    resolved = AptResolver(runner).resolve(Dep("numpy"))
    assert resolved is not None
    assert resolved.chosen_source == Source.APT
    assert resolved.apt_pkg == "python3-numpy"
    assert resolved.resolved_version == "1:1.24.2-1ubuntu1"


def test_pip_resolver_parses_uv_compile_version(tmp_path: Path) -> None:
    assert parse_pip_version("ml-collections", fixture("uv_compile_ml_collections.txt")) == "0.1.1"

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd[:3] == ["uv", "pip", "compile"]
        assert kwargs["input"] == "ml-collections>=0.1.1"
        return completed(cmd, fixture("uv_compile_ml_collections.txt"))

    dep = Dep("ml-collections", ">=0.1.1", Source.PIP)
    resolved = PipResolver(tmp_path / "venv", runner).resolve(dep)
    assert resolved is not None
    assert resolved.chosen_source == Source.PIP
    assert resolved.resolved_version == "0.1.1"


def test_resolution_manager_order_and_cache(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if cmd[:3] == ["rosdep", "resolve", "numpy"]:
            return completed(cmd, fixture("rosdep_apt_numpy.txt"))
        if cmd[:3] == ["rosdep", "resolve", "ml_collections"]:
            return completed(cmd, "", returncode=1)
        if cmd == ["apt-cache", "policy", "python3-ml-collections"]:
            return completed(cmd, fixture("apt_policy_missing.txt"))
        if cmd[:3] == ["uv", "pip", "compile"]:
            return completed(cmd, fixture("uv_compile_ml_collections.txt"))
        return completed(cmd, "", returncode=1)

    manager = ResolutionManager(
        ros_distro="humble",
        venv=tmp_path / "venv",
        modules={"rclpy"},
        runner=runner,
    )

    rclpy = manager.resolve(Dep("rclpy", source_hint=Source.ROSDEP))
    numpy = manager.resolve(Dep("numpy", source_hint=Source.ROSDEP))
    ml = manager.resolve(Dep("ml_collections", ">=0.1.1"))
    again = manager.resolve(Dep("ml_collections", ">=0.1.1"))

    assert rclpy is not None and rclpy.chosen_source == Source.DISTRO
    assert numpy is not None and numpy.chosen_source == Source.APT
    assert ml is not None and ml.chosen_source == Source.PIP
    assert again is ml
    assert calls.count(["apt-cache", "policy", "python3-ml-collections"]) == 1
