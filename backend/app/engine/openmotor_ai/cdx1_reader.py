from __future__ import annotations

from dataclasses import dataclass
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class RasaeroDimensions:
    length_in: float
    max_diameter_in: float


def _float_or_zero(text: str | None) -> float:
    if text is None:
        return 0.0
    try:
        return float(text)
    except Exception:
        return 0.0


def read_cdx1_dimensions(path: str) -> RasaeroDimensions:
    tree = ET.parse(path)
    root = tree.getroot()

    length_in = 0.0
    max_diameter_in = 0.0

    for node in root.iter():
        tag = node.tag.lower()
        if tag in ("nosecone", "bodytube", "booster"):
            length_in += _float_or_zero(node.findtext("Length"))
            max_diameter_in = max(max_diameter_in, _float_or_zero(node.findtext("Diameter")))

    return RasaeroDimensions(length_in=length_in, max_diameter_in=max_diameter_in)
