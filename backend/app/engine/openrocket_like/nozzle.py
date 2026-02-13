from __future__ import annotations

from app.engine.openrocket_like.models import NozzleConfig


def validate_nozzle(nozzle: NozzleConfig) -> None:
    if nozzle.throat_diameter_m <= 0:
        raise ValueError("throat_diameter_m must be > 0")
    if nozzle.exit_diameter_m <= 0:
        raise ValueError("exit_diameter_m must be > 0")
    if nozzle.exit_diameter_m < nozzle.throat_diameter_m:
        raise ValueError("exit_diameter_m must be >= throat_diameter_m")
    if nozzle.conv_angle_deg <= 0 or nozzle.div_angle_deg <= 0:
        raise ValueError("nozzle angles must be positive")

