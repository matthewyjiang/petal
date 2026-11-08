from __future__ import annotations

import json
from pathlib import Path

from petal.system import SystemPython, SystemView, parse_inspection


def test_parse_inspection_canonicalizes_and_drops_unpinnable_versions() -> None:
    output = json.dumps(
        {
            "distributions": {"PyYAML": "6.0.1", "weird": "not a version"},
            "modules": ["yaml", "rclpy"],
        }
    )

    python = parse_inspection(output)

    assert python.distributions == {"pyyaml": "6.0.1"}
    assert python.modules == {"yaml", "rclpy"}


def test_constraints_pin_system_packages_except_allowed_shadows(tmp_path: Path) -> None:
    constraints = tmp_path / ".petal" / "constraints.txt"
    view = SystemView(
        lambda: SystemPython({"numpy": "1.24.2", "pyyaml": "6.0.1"}),
        constraints_path=constraints,
        allow_shadow=["NumPy"],
    )

    assert view.constraint_args() == ["--constraints", str(constraints)]
    assert constraints.read_text(encoding="utf-8").splitlines()[1:] == ["pyyaml==6.0.1"]
    assert view.protects("PyYAML")
    assert not view.protects("numpy")
    assert view.version("numpy") == "1.24.2"


def test_refresh_rewrites_constraints_only_when_the_system_changed(
    tmp_path: Path,
) -> None:
    constraints = tmp_path / "constraints.txt"
    snapshots = [SystemPython({"numpy": "1.24.2"}), SystemPython({"numpy": "1.24.2"})]
    snapshots.append(SystemPython({"numpy": "1.24.2", "scipy": "1.8.0"}))
    view = SystemView(lambda: snapshots.pop(0), constraints_path=constraints)

    assert view.refresh() is False
    assert view.refresh() is True
    assert "scipy==1.8.0" in constraints.read_text(encoding="utf-8").splitlines()


def test_shadowed_by_ignores_venv_seed_packages() -> None:
    view = SystemView(
        lambda: SystemPython({"setuptools": "59.6.0", "numpy": "1.24.2"}),
        constraints_path=None,
    )

    installed = {"setuptools": "59.6.0", "numpy": "2.1.0", "rich": "15.0.0"}

    assert view.shadowed_by(installed) == {"numpy": "2.1.0"}
