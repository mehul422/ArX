from __future__ import annotations

from app.engine.openmotor_ai.eng_parser import EngData, EngHeader


def _format_float(value: float) -> str:
    rounded = round(value * 2.0) / 2.0
    if abs(rounded - int(rounded)) < 1e-9:
        return str(int(rounded))
    return f"{rounded:.1f}"


def _header_tokens(header: EngHeader) -> list[str]:
    tokens = [
        header.designation,
        _format_float(header.diameter_mm),
        _format_float(header.length_mm),
        header.motor_type,
    ]
    tokens.extend(_format_float(value) for value in header.header_values)
    if header.manufacturer:
        tokens.append(header.manufacturer)
    return tokens


def export_eng(eng: EngData) -> str:
    lines = []
    lines.append(" ".join(_header_tokens(eng.header)))
    for time_s, thrust_n in eng.curve:
        lines.append(f"{_format_float(time_s)} {_format_float(thrust_n)}")
    lines.append(";")
    lines.append(";")
    return "\n".join(lines) + "\n"
