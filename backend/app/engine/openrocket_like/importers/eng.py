from __future__ import annotations

from app.engine.openrocket_like.importers.base import MotorImportResult
from app.engine.openrocket_like.models import MotorRecord
from app.engine.openmotor_ai.eng_parser import load_eng


def _extract_propellant_label(path: str) -> str | None:
    label = None
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            line = line.strip()
            if not line.startswith(";") and not line.startswith("#"):
                continue
            lower = line.lower()
            if "propellant" in lower:
                parts = line.split(":", 1)
                if len(parts) == 2:
                    label = parts[1].strip()
                else:
                    label = line.replace(";", "").replace("#", "").strip()
                break
    return label


def import_eng(path: str) -> MotorImportResult:
    data = load_eng(path)
    diameter_m = data.header.diameter_mm / 1000.0
    length_m = data.header.length_mm / 1000.0
    propellant_label = _extract_propellant_label(path)
    delays = [value for value in data.header.header_values if value > 0]
    record = MotorRecord(
        designation=data.header.designation,
        diameter_m=diameter_m,
        length_m=length_m,
        motor_type=data.header.motor_type,
        manufacturer=data.header.manufacturer,
        propellant_label=propellant_label,
        delays_s=delays,
        thrust_curve=data.curve,
        source="eng",
        metadata={},
    )
    warnings: list[str] = []
    if propellant_label is None:
        warnings.append("propellant label missing in .eng comments")
    return MotorImportResult(record=record, warnings=warnings)

