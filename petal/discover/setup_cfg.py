from __future__ import annotations

import ast
import configparser
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement
from petal.identity import pip_name
from petal.models import Dep, Source


def _dep_from_requirement(raw: str, origin: str) -> Dep | None:
    text = raw.strip()
    if not text or text.startswith("#"):
        return None
    try:
        req = Requirement(text)
    except InvalidRequirement:
        return None
    return Dep(
        name=pip_name(req.name),
        version_spec=str(req.specifier),
        source_hint=Source.PIP,
        origin_packages=[origin],
    )


def parse_setup_cfg(setup_cfg: Path, origin: str) -> list[Dep]:
    parser = configparser.ConfigParser()
    parser.read(setup_cfg, encoding="utf-8")
    if not parser.has_option("options", "install_requires"):
        return []
    raw = parser.get("options", "install_requires")
    deps: list[Dep] = []
    for line in raw.splitlines():
        dep = _dep_from_requirement(line, origin)
        if dep:
            deps.append(dep)
    return deps


def parse_setup_py(setup_py: Path, origin: str) -> list[Dep]:
    tree = ast.parse(setup_py.read_text(encoding="utf-8"), filename=str(setup_py))
    deps: list[Dep] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg != "install_requires":
                continue
            try:
                values = ast.literal_eval(keyword.value)
            except (ValueError, SyntaxError):
                return deps
            if not isinstance(values, list):
                return deps
            for value in values:
                if isinstance(value, str):
                    dep = _dep_from_requirement(value, origin)
                    if dep:
                        deps.append(dep)
            return deps
    return deps
