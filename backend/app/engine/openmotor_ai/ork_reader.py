from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class RocketDimensions:
    length_m: float
    max_diameter_m: float


def _float_or_none(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _max_radius_from_nodes(root: ET.Element) -> float:
    max_radius = 0.0
    for tag in ("radius", "outerradius", "aftradius"):
        for node in root.iter(tag):
            value = _float_or_none(node.text)
            if value is not None:
                max_radius = max(max_radius, value)
    for node in root.iter("diameter"):
        value = _float_or_none(node.text)
        if value is not None:
            max_radius = max(max_radius, value / 2.0)
    return max_radius


def _stage_length(stage: ET.Element) -> float:
    total = 0.0
    for child in list(stage.find("subcomponents") or []):
        length_node = child.find("length")
        value = _float_or_none(length_node.text if length_node is not None else None)
        if value is not None:
            total += value
    return total


def read_rocket_dimensions(path: str) -> RocketDimensions:
    tree = ET.parse(path)
    root = tree.getroot()
    max_radius = _max_radius_from_nodes(root)

    length = 0.0
    stages = list(root.iter("stage"))
    if stages:
        length = max(_stage_length(stage) for stage in stages)
    else:
        for node in root.iter("length"):
            value = _float_or_none(node.text)
            if value is not None:
                length += value

    return RocketDimensions(length_m=length, max_diameter_m=max_radius * 2.0)
