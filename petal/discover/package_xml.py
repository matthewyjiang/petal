from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from petal.models import Dep, Source

DEPEND_TAGS = {
    "depend",
    "exec_depend",
    "build_depend",
    "build_export_depend",
    "test_depend",
}


def package_name(package_xml: Path) -> str:
    root = ET.parse(package_xml).getroot()
    node = root.find("name")
    if node is None or not (node.text or "").strip():
        return package_xml.parent.name
    return node.text.strip()


def condition_context(ros_distro: str) -> dict[str, str]:
    """Variables rosdep/colcon set when evaluating package.xml conditions."""
    return {"ROS_VERSION": "2", "ROS_PYTHON_VERSION": "3", "ROS_DISTRO": ros_distro}


def parse_package_xml(
    package_xml: Path, context: dict[str, str] | None = None
) -> list[Dep]:
    """Return rosdep keys from depend tags whose `condition` holds in `context`."""
    context = context if context is not None else condition_context("")
    root = ET.parse(package_xml).getroot()
    origin = package_name(package_xml)
    deps: list[Dep] = []
    for node in root:
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in DEPEND_TAGS:
            continue
        name = (node.text or "").strip()
        if not name:
            continue
        condition = node.get("condition")
        if condition and not evaluate_condition(condition, context):
            continue
        deps.append(Dep(name=name, source_hint=Source.ROSDEP, origin_packages=[origin]))
    return deps


_TOKEN_RE = re.compile(r"""\s*("[^"]*"|'[^']*'|==|!=|>=|<=|>|<|\(|\)|[^\s()=!<>"']+)""")
_COMPARISONS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
}


def evaluate_condition(condition: str, context: dict[str, str]) -> bool:
    """Evaluate a REP 149 condition such as `$ROS_VERSION == 2 and $X != y`.

    Values compare as strings and unset `$VARS` are empty, matching catkin_pkg.
    Unparseable conditions return True so the dep stays visible rather than
    silently disappearing.
    """
    text = condition.strip()
    tokens: list[str] = []
    pos = 0
    while pos < len(text):
        match = _TOKEN_RE.match(text, pos)
        if not match:
            return True
        tokens.append(match.group(1))
        pos = match.end()

    def value(token: str) -> str:
        if token.startswith("$"):
            return context.get(token[1:], "")
        if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
            return token[1:-1]
        return token

    def parse_or(i: int) -> tuple[bool, int]:
        result, i = parse_and(i)
        while i < len(tokens) and tokens[i] == "or":
            rhs, i = parse_and(i + 1)
            result = result or rhs
        return result, i

    def parse_and(i: int) -> tuple[bool, int]:
        result, i = parse_atom(i)
        while i < len(tokens) and tokens[i] == "and":
            rhs, i = parse_atom(i + 1)
            result = result and rhs
        return result, i

    def parse_atom(i: int) -> tuple[bool, int]:
        if tokens[i] == "(":
            result, i = parse_or(i + 1)
            if tokens[i] != ")":
                raise ValueError(condition)
            return result, i + 1
        lhs, op, rhs = tokens[i : i + 3]
        if op not in _COMPARISONS:
            raise ValueError(condition)
        return _COMPARISONS[op](value(lhs), value(rhs)), i + 3

    try:
        result, end = parse_or(0)
    except (IndexError, ValueError):
        return True
    return result if end == len(tokens) else True
