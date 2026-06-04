from __future__ import annotations

import pytest

from petal.models import Dep, ResolvedDep, Source
from petal.planner import PlannerConflict, build_plan, specs_compatible


def resolved(
    name: str,
    source: Source,
    spec: str = "",
    origin: str = "pkg",
    apt_pkg: str = "",
) -> ResolvedDep:
    return ResolvedDep(
        dep=Dep(name=name, version_spec=spec, origin_packages=[origin]),
        chosen_source=source,
        apt_pkg=apt_pkg,
    )


def test_specs_compatible_common_ranges() -> None:
    assert specs_compatible([">=1.24", "<2", "!=1.25"])
    assert specs_compatible([">=1.24", "==1.24.2"])
    assert not specs_compatible([">=1.24", "==1.21"])
    assert not specs_compatible([">=2", "<2"])
    assert not specs_compatible([">1", "<=1"])


def test_build_plan_partitions_sources() -> None:
    plan = build_plan(
        [
            resolved("rclpy", Source.DISTRO),
            resolved("numpy", Source.APT, apt_pkg="python3-numpy"),
            resolved("rich", Source.PIP, ">=13"),
        ]
    )
    assert [item.dep.name for item in plan.distro] == ["rclpy"]
    assert [item.apt_pkg for item in plan.apt] == ["python3-numpy"]
    assert [item.dep.name for item in plan.pip] == ["rich"]
    assert plan.warnings == []


def test_conflicting_specs_raise_with_origins() -> None:
    with pytest.raises(PlannerConflict) as exc:
        build_plan(
            [
                resolved("numpy", Source.PIP, ">=1.24", "pkg_a"),
                resolved("NumPy", Source.PIP, "==1.21", "pkg_b"),
            ]
        )
    message = str(exc.value)
    assert "numpy" in message
    assert "pkg_a needs numpy>=1.24" in message
    assert "pkg_b needs NumPy==1.21" in message


def test_compatible_specs_merge_without_error() -> None:
    plan = build_plan(
        [
            resolved("numpy", Source.PIP, ">=1.24", "pkg_a"),
            resolved("NumPy", Source.PIP, "<2", "pkg_b"),
        ]
    )
    assert [item.dep.name for item in plan.pip] == ["numpy", "NumPy"]


def test_shadow_warning_for_pip_and_apt_same_name() -> None:
    plan = build_plan(
        [
            resolved("numpy", Source.APT, ">=1.24", "pkg_a", "python3-numpy"),
            resolved("NumPy", Source.PIP, "<2", "pkg_b"),
        ]
    )
    assert len(plan.warnings) == 1
    assert "shadowing" in plan.warnings[0]
    assert "numpy" in plan.warnings[0]


def test_incompatible_shadow_conflict_still_fails_before_install() -> None:
    with pytest.raises(PlannerConflict):
        build_plan(
            [
                resolved("numpy", Source.APT, "==1.24", "pkg_a", "python3-numpy"),
                resolved("NumPy", Source.PIP, "==1.21", "pkg_b"),
            ]
        )
