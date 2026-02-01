from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EngHeader:
    designation: str
    diameter_mm: float
    length_mm: float
    motor_type: str
    header_values: list[float]
    manufacturer: str | None


@dataclass(frozen=True)
class EngData:
    header: EngHeader
    curve: list[tuple[float, float]]


def _parse_header(tokens: list[str]) -> EngHeader:
    if len(tokens) < 4:
        raise ValueError("Invalid .eng header")
    designation = tokens[0]
    diameter_mm = float(tokens[1])
    length_mm = float(tokens[2])
    motor_type = tokens[3]
    header_values: list[float] = []
    manufacturer = None
    for token in tokens[4:]:
        try:
            header_values.append(float(token))
        except ValueError:
            manufacturer = token
            break
    return EngHeader(
        designation=designation,
        diameter_mm=diameter_mm,
        length_mm=length_mm,
        motor_type=motor_type,
        header_values=header_values,
        manufacturer=manufacturer,
    )


def load_eng(path: str) -> EngData:
    curve: list[tuple[float, float]] = []
    header: EngHeader | None = None
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            if line.startswith(";"):
                break
            parts = line.split()
            if header is None:
                header = _parse_header(parts)
                continue
            if len(parts) != 2:
                continue
            curve.append((float(parts[0]), float(parts[1])))
    if header is None:
        raise ValueError("Missing .eng header")
    if not curve:
        raise ValueError("Missing .eng thrust curve")
    return EngData(header=header, curve=curve)
