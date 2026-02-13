from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EngMotorDefinition:
    name: str
    diameter_m: float
    length_m: float
    total_impulse_ns: float
    burn_time_s: float
    propellant_mass_kg: float | None
    total_mass_kg: float | None
    thrust_curve: list[tuple[float, float]]


def _parse_float(value: str) -> float:
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(f"invalid numeric value: {value}") from exc


def _is_float(value: str) -> bool:
    try:
        float(value)
        return True
    except Exception:
        return False


def parse_eng_file(path: str) -> EngMotorDefinition:
    with open(path, "r", encoding="utf-8", errors="ignore") as handle:
        lines = [line.strip() for line in handle.readlines() if line.strip()]

    header = None
    curve: list[tuple[float, float]] = []
    for line in lines:
        if line.startswith(";") or line.startswith("#"):
            continue
        if header is None:
            header = line
            continue
        parts = line.split()
        if len(parts) >= 2:
            t = _parse_float(parts[0])
            thrust = _parse_float(parts[1])
            curve.append((t, thrust))

    if header is None:
        raise ValueError("missing .eng header line")

    header_parts = header.split()
    if len(header_parts) < 6:
        raise ValueError("invalid .eng header format")

    diameter_index = None
    for idx, token in enumerate(header_parts):
        if _is_float(token):
            diameter_index = idx
            break
    if diameter_index is None or diameter_index + 4 >= len(header_parts):
        raise ValueError("invalid .eng header format")

    name_tokens = header_parts[:diameter_index]
    name = " ".join(name_tokens) if name_tokens else header_parts[0]

    diameter_mm = _parse_float(header_parts[diameter_index])
    length_mm = _parse_float(header_parts[diameter_index + 1])
    propellant_mass_kg = _parse_float(header_parts[diameter_index + 3])
    total_mass_kg = _parse_float(header_parts[diameter_index + 4])

    diameter_m = diameter_mm / 1000.0
    length_m = length_mm / 1000.0

    total_impulse = 0.0
    for idx in range(1, len(curve)):
        t0, f0 = curve[idx - 1]
        t1, f1 = curve[idx]
        total_impulse += (t1 - t0) * (f0 + f1) / 2.0

    burn_time = curve[-1][0] if curve else 0.0

    return EngMotorDefinition(
        name=name,
        diameter_m=diameter_m,
        length_m=length_m,
        total_impulse_ns=total_impulse,
        burn_time_s=burn_time,
        propellant_mass_kg=propellant_mass_kg,
        total_mass_kg=total_mass_kg,
        thrust_curve=curve,
    )
