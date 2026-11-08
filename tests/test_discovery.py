from __future__ import annotations

from pathlib import Path

from petal.discover.package_xml import parse_package_xml
from petal.discover.setup_cfg import parse_setup_py
from petal.discover.workspace import discover_workspace
from petal.models import Source

FIXTURES = Path(__file__).parent / "fixtures"


def dep_map(deps):  # type: ignore[no-untyped-def]
    return {dep.name: dep for dep in deps}


def test_package_xml_parses_rosdep_keys() -> None:
    deps = parse_package_xml(
        FIXTURES / "ws_discovery" / "src" / "pkg_a" / "package.xml"
    )
    names = [dep.name for dep in deps]
    assert names == ["rclpy", "numpy", "pytest"]
    assert all(dep.source_hint == Source.ROSDEP for dep in deps)
    assert all(dep.origin_packages == ["pkg_a"] for dep in deps)


def test_workspace_discovers_and_merges_deps() -> None:
    result = discover_workspace(FIXTURES / "ws_discovery")
    deps = dep_map(result.deps)

    assert set(deps) == {
        "ml-collections",
        "numpy",
        "pytest",
        "rclpy",
        "requests",
        "rich",
    }
    assert "should_not_appear" not in deps

    assert deps["rclpy"].source_hint == Source.ROSDEP
    assert deps["numpy"].source_hint == Source.ROSDEP
    assert deps["requests"].source_hint == Source.PIP
    assert deps["requests"].version_spec == ">=2.31"
    assert deps["rich"].source_hint == Source.PIP
    assert deps["rich"].version_spec == ">=13"

    assert deps["ml-collections"].source_hint == Source.PIP
    assert deps["ml-collections"].origin_packages == ["pkg_a", "pkg_b"]
    assert deps["pytest"].origin_packages == ["pkg_a", "pkg_b"]


def test_workspace_returns_per_package_map() -> None:
    result = discover_workspace(FIXTURES / "ws_discovery" / "src" / "pkg_a")
    assert set(result.by_package) == {"pkg_a", "pkg_b"}
    assert [dep.name for dep in result.by_package["pkg_a"]] == [
        "rclpy",
        "numpy",
        "pytest",
        "requests",
        "ml-collections",
    ]


def test_static_setup_py_literal_is_parsed() -> None:
    setup_py = FIXTURES / "ws_setup_py" / "src" / "pkg_setup_py" / "setup.py"
    deps = dep_map(parse_setup_py(setup_py, "pkg_setup_py"))
    assert deps["httpx"].version_spec == ">=0.27"
    assert deps["pyyaml"].version_spec == "==6.0.1"
    assert deps["pyyaml"].source_hint == Source.PIP


def test_no_src_workspace_is_empty(tmp_path: Path) -> None:
    result = discover_workspace(tmp_path)
    assert result.deps == []
    assert result.by_package == {}


def test_workspace_packages_are_not_external_deps() -> None:
    result = discover_workspace(FIXTURES / "ws_local_deps")
    names = {dep.name for dep in result.deps}

    # pkg_msgs is built by colcon from this workspace, whether referenced as a
    # package.xml key or as a PEP 503 variant in install_requires.
    assert "pkg_msgs" not in names
    assert "pkg-msgs" not in names
    assert [dep.name for dep in result.by_package["pkg_app"]] == [
        "rosidl_default_runtime",
        "rclcpp_components",
        "requests",
    ]


def test_rosdep_keys_keep_their_exact_spelling() -> None:
    deps = dep_map(discover_workspace(FIXTURES / "ws_local_deps").deps)

    assert set(deps) == {
        "rclcpp_components",
        "requests",
        "rosidl_default_generators",
        "rosidl_default_runtime",
    }
    assert deps["rclcpp_components"].source_hint == Source.ROSDEP
