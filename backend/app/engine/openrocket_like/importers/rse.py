from __future__ import annotations

from xml.etree import ElementTree

from app.engine.openrocket_like.importers.base import MotorImportResult
from app.engine.openrocket_like.models import MotorRecord


def _find_engines(root: ElementTree.Element) -> list[ElementTree.Element]:
    engines = root.findall(".//engine")
    if engines:
        return engines
    return root.findall(".//motor")


def _parse_float(value: str | None, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def import_rse(path: str) -> MotorImportResult:
    tree = ElementTree.parse(path)
    root = tree.getroot()
    engines = _find_engines(root)
    if not engines:
        raise ValueError("no engines found in .rse file")

    engine = engines[0]
    designation = engine.attrib.get("designation") or engine.attrib.get("name") or "imported"
    motor_type = engine.attrib.get("type") or "P"
    manufacturer = engine.attrib.get("manufacturer")
    propellant_label = engine.attrib.get("propellant")
    diameter_m = _parse_float(engine.attrib.get("dia"), 0.0) / 1000.0
    length_m = _parse_float(engine.attrib.get("len"), 0.0) / 1000.0
    delays_raw = engine.attrib.get("delays", "")
    delays = []
    for part in delays_raw.replace(",", " ").split():
        value = _parse_float(part, 0.0)
        if value > 0:
            delays.append(value)

    curve: list[tuple[float, float]] = []
    for datapoint in engine.findall(".//data"):
        t = _parse_float(datapoint.attrib.get("t"))
        f = _parse_float(datapoint.attrib.get("f"))
        if t > 0 or f > 0:
            curve.append((t, f))
    if not curve:
        for datapoint in engine.findall(".//point"):
            t = _parse_float(datapoint.attrib.get("time"))
            f = _parse_float(datapoint.attrib.get("thrust"))
            if t > 0 or f > 0:
                curve.append((t, f))

    if not curve:
        raise ValueError("missing thrust curve in .rse file")

    record = MotorRecord(
        designation=designation,
        diameter_m=diameter_m,
        length_m=length_m,
        motor_type=motor_type,
        manufacturer=manufacturer,
        propellant_label=propellant_label,
        delays_s=delays,
        thrust_curve=curve,
        source="rse",
        metadata={},
    )
    warnings: list[str] = []
    if propellant_label is None:
        warnings.append("propellant label missing in .rse metadata")
    return MotorImportResult(record=record, warnings=warnings)

