from __future__ import annotations

from app.engine.openrocket_like_legacy.models import GrainGeometry, GrainGeometryType


_REQUIRED_PARAMS: dict[GrainGeometryType, set[str]] = {
    GrainGeometryType.BATES: {"diameter_m", "core_diameter_m", "length_m", "grain_count"},
    GrainGeometryType.FINOCYL: {"diameter_m", "core_diameter_m", "length_m", "fin_count", "fin_width_m"},
    GrainGeometryType.MOON: {"diameter_m", "core_diameter_m", "length_m", "offset_m"},
    GrainGeometryType.SLOT: {"diameter_m", "slot_width_m", "length_m"},
    GrainGeometryType.STAR: {"diameter_m", "core_diameter_m", "length_m", "point_count"},
    GrainGeometryType.CUSTOM: set(),
}


def validate_grain_geometry(geometry: GrainGeometry) -> None:
    if geometry.type not in _REQUIRED_PARAMS:
        raise ValueError(f"unsupported grain geometry: {geometry.type}")
    required = _REQUIRED_PARAMS[geometry.type]
    missing = [key for key in required if key not in geometry.params]
    if missing:
        raise ValueError(f"missing grain parameters: {', '.join(sorted(missing))}")
    for key, value in geometry.params.items():
        if value <= 0 and key not in {"offset_m"}:
            raise ValueError(f"invalid grain parameter {key}: {value}")
    if geometry.type == GrainGeometryType.BATES:
        core = geometry.params["core_diameter_m"]
        diam = geometry.params["diameter_m"]
        if core >= diam:
            raise ValueError("core_diameter_m must be smaller than diameter_m")
        if geometry.params["grain_count"] < 1:
            raise ValueError("grain_count must be >= 1")
