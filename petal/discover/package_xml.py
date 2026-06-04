from __future__ import annotations

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


def parse_package_xml(package_xml: Path) -> list[Dep]:
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
        deps.append(Dep(name=name, source_hint=Source.ROSDEP, origin_packages=[origin]))
    return deps
