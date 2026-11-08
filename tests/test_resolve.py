from __future__ import annotations

import subprocess
from pathlib import Path

from petal.models import Dep, Source
from petal.resolve.apt import AptResolver, _candidate_version
from petal.resolve.base import canonical, python_apt_name
from petal.resolve.distro import DistroResolver
from petal.resolve.manager import ResolutionManager
from petal.resolve.pip import PipResolver, parse_pins
from petal.resolve.rosdep import RosdepResolver, parse_rosdep_resolve
from petal.system import SystemPython, SystemView

FIXTURES = Path(__file__).parent / "fixtures" / "cmd_output"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def completed(
    cmd: list[str], stdout: str, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)


def system(
    distributions: dict[str, str] | None = None,
    modules: set[str] | None = None,
    allow_shadow: tuple[str, ...] = (),
    constraints_path: Path | None = None,
) -> SystemView:
    python = SystemPython(distributions or {}, frozenset(modules or ()))
    return SystemView(
        lambda: python, constraints_path=constraints_path, allow_shadow=allow_shadow
    )


def test_canonical_helpers() -> None:
    assert canonical("ml_collections") == "ml-collections"
    assert canonical("Foo_Bar") == "foo-bar"
    assert python_apt_name("NumPy") == "python3-numpy"
    assert python_apt_name("python3-numpy") == "python3-numpy"


def test_distro_resolver_short_circuits_rclpy() -> None:
    resolver = DistroResolver(system(modules={"rclpy", "launch"}))
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

    resolved = RosdepResolver("humble", runner).resolve(
        Dep("numpy", source_hint=Source.ROSDEP)
    )
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


def test_parse_pins_reads_compile_output() -> None:
    pins = parse_pins(
        fixture("uv_compile_ml_collections.txt")
        + "Foo_Bar[extra]==1.0 ; python_version >= '3.8'\n"
        + "baz @ git+https://example.com/baz.git\n"
    )
    assert [(pin.name, pin.version) for pin in pins] == [
        ("ml-collections", "0.1.1"),
        ("absl-py", "2.1.0"),
        ("foo-bar", "1.0"),
        ("baz", ""),
    ]
    assert pins[-1].requirement == "baz @ git+https://example.com/baz.git"


def test_pip_resolver_compiles_against_system_constraints(tmp_path: Path) -> None:
    constraints = tmp_path / ".petal" / "constraints.txt"
    view = system({"numpy": "1.24.2"}, constraints_path=constraints)

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd[:3] == ["uv", "pip", "compile"]
        assert cmd[cmd.index("--constraints") + 1] == str(constraints)
        assert kwargs["input"] == "ml-collections>=0.1.1\n"
        return completed(cmd, fixture("uv_compile_ml_collections.txt"))

    dep = Dep("ml-collections", ">=0.1.1", Source.PIP)
    resolved = PipResolver(tmp_path / "venv", view, runner).resolve(dep)
    assert "numpy==1.24.2" in constraints.read_text(encoding="utf-8").splitlines()
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
        system=system(modules={"rclpy"}),
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


def test_unknown_rosdep_key_is_never_looked_up_on_pypi(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if cmd[0] == "rosdep":
            return completed(cmd, fixture("rosdep_missing.txt"), returncode=1)
        # A squatted PyPI project would happily "resolve" here.
        return completed(cmd, "my-typo-dep==6.6.6\n")

    manager = ResolutionManager(
        ros_distro="humble", venv=tmp_path / "venv", system=system(), runner=runner
    )

    dep = Dep("my_typo_dep", source_hint=Source.ROSDEP, origin_packages=["pkg_a"])
    assert manager.resolve(dep) is None
    assert calls == [["rosdep", "resolve", "my_typo_dep", "--rosdistro", "humble"]]


def _no_pypi(cmd, **kwargs):  # type: ignore[no-untyped-def]
    raise AssertionError(f"unexpected command: {cmd}")


def test_python_requirement_provided_by_system_is_not_installed(tmp_path: Path) -> None:
    manager = ResolutionManager(
        ros_distro="humble",
        venv=tmp_path / "venv",
        system=system({"numpy": "1.24.2"}),
        runner=_no_pypi,
    )

    resolved = manager.resolve(Dep("NumPy", ">=1.20", Source.PIP, ["pkg_a"]))

    assert resolved is not None
    assert resolved.chosen_source == Source.DISTRO
    assert resolved.resolved_version == "1.24.2"


def test_python_requirement_conflicting_with_system_fails_with_reason(
    tmp_path: Path,
) -> None:
    uv_error = "Because you require numpy>=2 and numpy==1.24.2, ... unsatisfiable."

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd[:3] == ["uv", "pip", "compile"]
        return completed(cmd, "", returncode=1, stderr=uv_error)

    manager = ResolutionManager(
        ros_distro="humble",
        venv=tmp_path / "venv",
        system=system({"numpy": "1.24.2"}),
        runner=runner,
    )
    dep = Dep("numpy", ">=2", Source.PIP, ["pkg_a"])

    assert manager.resolve(dep) is None
    reason = manager.failure_reason(dep)
    assert "the system provides numpy 1.24.2" in reason
    assert uv_error in reason


def test_explicit_pip_dep_may_shadow_system_copy(tmp_path: Path) -> None:
    constraints = tmp_path / "constraints.txt"

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return completed(cmd, "numpy==2.1.0\n")

    manager = ResolutionManager(
        ros_distro="humble",
        venv=tmp_path / "venv",
        system=system(
            {"numpy": "1.24.2", "pyyaml": "6.0.1"},
            allow_shadow=("numpy",),
            constraints_path=constraints,
        ),
        runner=runner,
    )

    resolved = manager.resolve(Dep("numpy", ">=2", Source.PIP))

    assert resolved is not None
    assert resolved.chosen_source == Source.PIP
    assert resolved.resolved_version == "2.1.0"
    pins = constraints.read_text(encoding="utf-8").splitlines()
    assert "pyyaml==6.0.1" in pins
    assert not any(line.startswith("numpy") for line in pins)


def test_rosdep_pip_rule_prefers_system_copy(tmp_path: Path) -> None:
    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd[0] == "rosdep"
        return completed(cmd, fixture("rosdep_pip_ml_collections.txt"))

    manager = ResolutionManager(
        ros_distro="humble",
        venv=tmp_path / "venv",
        system=system({"ml-collections": "0.1.1"}),
        runner=runner,
    )

    resolved = manager.resolve(Dep("ml_collections", source_hint=Source.ROSDEP))

    assert resolved is not None
    assert resolved.chosen_source == Source.DISTRO


def test_distro_resolver_checks_version_spec_for_bare_deps() -> None:
    resolver = DistroResolver(system({"numpy": "1.24.2"}))

    assert resolver.resolve(Dep("numpy", ">=2")) is None
    resolved = resolver.resolve(Dep("numpy", "<2"))
    assert resolved is not None and resolved.resolved_version == "1.24.2"
