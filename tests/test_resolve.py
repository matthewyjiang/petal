from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from packaging.requirements import Requirement

from petal.identity import pip_name, python_apt_package
from petal.models import Dep, ResolvedDep, Source
from petal.planner import PlannerConflict
from petal.resolve.apt import AptResolver, _candidate_version
from petal.resolve.base import dep_requirement, upstream_version
from petal.resolve.distro import DistroResolver
from petal.resolve.manager import (
    ResolutionManager,
    Unresolved,
    UnresolvedDependencies,
    lock_mismatch,
)
from petal.resolve.pip import parse_pins
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
    assert pip_name("ml_collections") == "ml-collections"
    assert pip_name("Foo_Bar") == "foo-bar"
    assert python_apt_package("NumPy") == "python3-numpy"
    assert python_apt_package("python3-numpy") == "python3-numpy"


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


def manager_for(tmp_path: Path, view: SystemView, runner) -> ResolutionManager:  # type: ignore[no-untyped-def]
    """Manager over an empty venv; other commands go to `runner`."""

    def route(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:3] == ["uv", "pip", "list"]:
            return uv_list(cmd)
        return runner(cmd, **kwargs)

    return ResolutionManager(
        ros_distro="humble", venv=tmp_path / "venv", system=view, runner=route
    )


def uv_compile(cmd, kwargs, versions: dict[str, str]):  # type: ignore[no-untyped-def]
    """Fake `uv pip compile`: pins each stdin requirement to `versions`."""
    names = [Requirement(line).name for line in kwargs["input"].splitlines()]
    write_output(cmd, "".join(f"{n}=={versions[n]}\n" for n in names))
    return completed(cmd, "")


def write_output(cmd: list[str], text: str) -> None:
    Path(cmd[cmd.index("--output-file") + 1]).write_text(text, encoding="utf-8")


def uv_list(cmd, installed: str = "[]"):  # type: ignore[no-untyped-def]
    return completed(cmd, installed)


def resolve_one(manager: ResolutionManager, dep: Dep) -> ResolvedDep:
    [resolved] = manager.resolve_all([dep])
    return resolved


def test_resolution_manager_source_order(tmp_path: Path) -> None:
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
            write_output(cmd, fixture("uv_compile_ml_collections.txt"))
            return completed(cmd, "")
        return completed(cmd, "", returncode=1)

    manager = manager_for(tmp_path, system(modules={"rclpy"}), runner)
    ml = Dep("ml_collections", ">=0.1.1")
    rclpy, numpy, ml_resolved, again, absl = manager.resolve_all(
        [
            Dep("rclpy", source_hint=Source.ROSDEP),
            Dep("numpy", source_hint=Source.ROSDEP),
            ml,
            ml,
        ]
    )

    assert rclpy.chosen_source == Source.DISTRO
    assert numpy.chosen_source == Source.APT
    assert ml_resolved.chosen_source == Source.PIP
    assert ml_resolved.resolved_version == "0.1.1"
    assert again == ml_resolved
    # The lock pins what ml_collections pulls in, too.
    assert absl == ResolvedDep(Dep("absl-py"), Source.PIP, "2.1.0", transitive=True)


def test_unknown_rosdep_key_is_never_looked_up_on_pypi(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(cmd)
        if cmd[0] == "rosdep":
            return completed(cmd, fixture("rosdep_missing.txt"), returncode=1)
        # A squatted PyPI project would happily "resolve" here.
        return completed(cmd, "my-typo-dep==6.6.6\n")

    dep = Dep("my_typo_dep", source_hint=Source.ROSDEP, origin_packages=["pkg_a"])
    with pytest.raises(UnresolvedDependencies) as exc:
        manager_for(tmp_path, system(), runner).resolve_all([dep])

    assert [f.dep for f in exc.value.failures] == [dep]
    assert calls == [["rosdep", "resolve", "my_typo_dep", "--rosdistro", "humble"]]


def _no_commands(cmd, **kwargs):  # type: ignore[no-untyped-def]
    raise AssertionError(f"unexpected command: {cmd}")


def test_python_requirement_provided_by_system_is_not_installed(tmp_path: Path) -> None:
    manager = manager_for(tmp_path, system({"numpy": "1.24.2"}), _no_commands)

    resolved = resolve_one(manager, Dep("NumPy", ">=1.20", Source.PIP, ["pkg_a"]))

    assert resolved.chosen_source == Source.DISTRO
    assert resolved.resolved_version == "1.24.2"


def test_python_requirement_conflicting_with_system_fails_with_reason(
    tmp_path: Path,
) -> None:
    manager = manager_for(tmp_path, system({"numpy": "1.24.2"}), _no_commands)
    dep = Dep("numpy", ">=2", Source.PIP, ["pkg_a"])

    with pytest.raises(UnresolvedDependencies) as exc:
        manager.resolve_all([dep])

    assert "the system provides numpy 1.24.2" in str(exc.value)
    assert "petal add --pip" in str(exc.value)


def test_pypi_deps_are_pinned_together_against_system_constraints(
    tmp_path: Path,
) -> None:
    constraints = tmp_path / ".petal" / "constraints.txt"
    view = system({"pygments": "2.18.0"}, constraints_path=constraints)
    compiles: list[str] = []

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd[cmd.index("--constraints") + 1] == str(constraints)
        compiles.append(kwargs["input"])
        return uv_compile(cmd, kwargs, {"rich": "15.0.0", "httpx": "0.28.1"})

    rich, httpx = manager_for(tmp_path, view, runner).resolve_all(
        [Dep("rich", "", Source.PIP), Dep("httpx", ">=0.27", Source.PIP)]
    )

    assert compiles == ["rich\nhttpx>=0.27\n"]
    assert (rich.resolved_version, httpx.resolved_version) == ("15.0.0", "0.28.1")
    assert "pygments==2.18.0" in constraints.read_text(encoding="utf-8").splitlines()


def test_pulled_in_direct_references_keep_their_url(tmp_path: Path) -> None:
    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        write_output(cmd, "foo==1.0\nbar @ git+https://example.com/bar\n")
        return completed(cmd, "")

    _, bar = manager_for(tmp_path, system(), runner).resolve_all(
        [Dep("foo", "", Source.PIP)]
    )

    assert dep_requirement(bar.dep) == "bar @ git+https://example.com/bar"
    assert bar.transitive


def test_pypi_failure_is_attributed_to_the_failing_dep(tmp_path: Path) -> None:
    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if "nonexistent" in kwargs["input"]:
            return completed(cmd, "", 1, stderr="nonexistent was not found")
        return uv_compile(cmd, kwargs, {"rich": "15.0.0"})

    bad = Dep("nonexistent", "", Source.PIP, ["pkg_a"])
    with pytest.raises(UnresolvedDependencies) as exc:
        manager_for(tmp_path, system(), runner).resolve_all(
            [Dep("rich", "", Source.PIP), bad]
        )

    assert exc.value.failures == [Unresolved(bad, "nonexistent was not found")]


def test_pypi_deps_that_conflict_only_together_raise_conflict(tmp_path: Path) -> None:
    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if len(kwargs["input"].splitlines()) > 1:
            return completed(cmd, "", 1, stderr="a needs b<2 and c needs b>=2")
        return uv_compile(cmd, kwargs, {"a": "1", "c": "1"})

    with pytest.raises(PlannerConflict, match="a needs b<2 and c needs b>=2"):
        manager_for(tmp_path, system(), runner).resolve_all(
            [Dep("a", "", Source.PIP), Dep("c", "", Source.PIP)]
        )


def test_explicit_pip_dep_may_shadow_system_copy(tmp_path: Path) -> None:
    constraints = tmp_path / "constraints.txt"
    view = system(
        {"numpy": "1.24.2", "pyyaml": "6.0.1"},
        allow_shadow=("numpy",),
        constraints_path=constraints,
    )
    runner = lambda cmd, **kwargs: uv_compile(cmd, kwargs, {"numpy": "2.1.0"})

    resolved = resolve_one(
        manager_for(tmp_path, view, runner), Dep("numpy", ">=2", Source.PIP)
    )

    assert resolved.chosen_source == Source.PIP
    assert resolved.resolved_version == "2.1.0"
    pins = constraints.read_text(encoding="utf-8").splitlines()
    assert "pyyaml==6.0.1" in pins
    assert not any(line.startswith("numpy") for line in pins)


def test_rosdep_pip_rule_prefers_system_copy(tmp_path: Path) -> None:
    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd[0] == "rosdep"
        return completed(cmd, fixture("rosdep_pip_ml_collections.txt"))

    view = system({"ml-collections": "0.1.1"})
    resolved = resolve_one(
        manager_for(tmp_path, view, runner),
        Dep("ml_collections", source_hint=Source.ROSDEP),
    )

    assert resolved.chosen_source == Source.DISTRO


def test_pypi_resolution_prefers_locked_and_installed_versions(tmp_path: Path) -> None:
    seen: dict[str, str] = {}

    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:3] == ["uv", "pip", "list"]:
            return uv_list(cmd, '[{"name": "mdurl", "version": "0.1.0"}]')
        output = Path(cmd[cmd.index("--output-file") + 1])
        seen["preferences"] = output.read_text(encoding="utf-8")
        return uv_compile(cmd, kwargs, {"rich": "13.7.0"})

    manager = ResolutionManager(
        ros_distro="humble",
        venv=tmp_path / "venv",
        system=system(),
        locked={"rich": "13.7.0"},
        runner=runner,
    )
    resolve_one(manager, Dep("rich", "", Source.PIP))

    assert seen["preferences"] == "mdurl==0.1.0\nrich==13.7.0\n"


def test_spec_conflicts_are_reported_with_origins_before_pinning(
    tmp_path: Path,
) -> None:
    deps = [
        Dep("rich", "<13", Source.PIP, ["pkg_a"]),
        Dep("rich", ">=13", Source.PIP, ["pkg_b"]),
    ]

    with pytest.raises(PlannerConflict, match="pkg_a needs rich<13; pkg_b needs"):
        manager_for(tmp_path, system(), _no_commands).resolve_all(deps)


def test_lock_mismatch_checks_what_each_entry_relied_on() -> None:
    locked = [
        ResolvedDep(Dep("numpy", ">=1.20", Source.PIP), Source.DISTRO),
        # From a rosdep `pip:` rule: the entry has the PyPI name, not the key.
        ResolvedDep(Dep("rich", "", Source.PIP), Source.PIP, resolved_version="13.7.0"),
    ]

    # A newer system numpy that still satisfies the spec keeps the lock valid.
    assert lock_mismatch(locked, system({"numpy": "1.26.4"})) == ""
    assert "which has 1.19.5" in lock_mismatch(locked, system({"numpy": "1.19.5"}))
    assert "does not provide it" in lock_mismatch(locked, system())
    assert lock_mismatch(locked, system(), check_distro=False) == ""
    assert "the system now provides 13.9.4" in lock_mismatch(
        locked, system({"numpy": "1.24.2", "rich": "13.9.4"}), check_distro=False
    )


def test_reselect_python_keeps_apt_choices(tmp_path: Path) -> None:
    deb = ResolvedDep(Dep("scipy"), Source.APT, apt_pkg="python3-scipy")
    mdurl = ResolvedDep(Dep("mdurl", "", Source.PIP), Source.PIP, "0.1.2")
    manager = manager_for(
        tmp_path, system({"scipy": "1.8.0", "mdurl": "0.1.2"}), _no_commands
    )

    kept, now_system = manager.reselect_python([deb, mdurl])

    assert kept == deb
    assert (now_system.chosen_source, now_system.resolved_version) == (
        Source.DISTRO,
        "0.1.2",
    )


def test_distro_resolver_checks_version_spec_for_bare_deps() -> None:
    resolver = DistroResolver(system({"numpy": "1.24.2"}))

    assert resolver.resolve(Dep("numpy", ">=2")) is None
    resolved = resolver.resolve(Dep("numpy", "<2"))
    assert resolved is not None and resolved.resolved_version == "1.24.2"


def test_apt_resolver_checks_version_spec_against_upstream_version() -> None:
    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return completed(cmd, fixture("apt_policy_numpy.txt"))  # 1:1.24.2-1ubuntu1

    resolver = AptResolver(runner)

    assert resolver.resolve(Dep("numpy", ">=2")) is None
    resolved = resolver.resolve(Dep("numpy", ">=1.24,<2"))
    assert resolved is not None and resolved.apt_pkg == "python3-numpy"


def test_upstream_version_strips_epoch_and_debian_revision() -> None:
    assert upstream_version("1:1.24.2-1ubuntu1") == "1.24.2"
    assert upstream_version("2.25.1+dfsg-2") == "2.25.1+dfsg"
    assert upstream_version("6.0.1") == "6.0.1"
    assert upstream_version("1.8.0~rc1-1") == "1.8.0rc1"
    assert upstream_version("2.0~git20200101-1") == ""


def test_apt_dep_does_not_hide_the_python_package_of_the_same_name(
    tmp_path: Path,
) -> None:
    def runner(cmd, **kwargs):  # type: ignore[no-untyped-def]
        if cmd[:3] == ["rosdep", "resolve", "protobuf"]:
            return completed(cmd, "#apt\nlibprotobuf-dev\n")
        write_output(cmd, "onnx==1.17.0\nprotobuf==5.29.0\n")
        return completed(cmd, "")

    *_, protobuf = manager_for(tmp_path, system(), runner).resolve_all(
        [Dep("protobuf", source_hint=Source.ROSDEP), Dep("onnx", "", Source.PIP)]
    )

    assert (protobuf.dep.name, protobuf.resolved_version) == ("protobuf", "5.29.0")
    assert protobuf.chosen_source == Source.PIP and protobuf.transitive
