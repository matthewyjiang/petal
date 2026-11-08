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
    loads: list[int] = []

    def load() -> SystemPython:
        loads.append(1)
        return SystemPython({"numpy": "1.24.2", "pyyaml": "6.0.1"})

    view = SystemView(load, constraints_path=constraints, allow_shadow=["NumPy"])
    assert loads == []  # nothing inspected until something asks

    assert view.constraints_file() == constraints
    assert constraints.read_text(encoding="utf-8").splitlines()[1:] == ["pyyaml==6.0.1"]
    assert view.protects("PyYAML")
    assert not view.protects("numpy")
    assert view.version("numpy") == "1.24.2"

    view.version("pyyaml")
    assert loads == [1]
    view.refresh()
    view.version("pyyaml")
    assert loads == [1, 1]
