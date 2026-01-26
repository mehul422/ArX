from typing import Any

import numpy as np


def _require_positive(value: float, name: str) -> float:
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def run_internal_ballistics(params: dict[str, Any]) -> dict[str, Any]:
    chamber_pressure = float(params.get("chamber_pressure", 3.0e6))
    burn_time = float(params.get("burn_time", 2.0))
    throat_area = float(params.get("throat_area", 0.0004))
    c_star = float(params.get("c_star", 1500.0))

    _require_positive(chamber_pressure, "chamber_pressure")
    _require_positive(burn_time, "burn_time")
    _require_positive(throat_area, "throat_area")
    _require_positive(c_star, "c_star")

    mass_flow = (chamber_pressure * throat_area) / c_star
    total_impulse = mass_flow * burn_time * c_star
    thrust = total_impulse / burn_time

    return {
        "chamber_pressure": chamber_pressure,
        "burn_time": burn_time,
        "throat_area": throat_area,
        "c_star": c_star,
        "mass_flow": float(np.round(mass_flow, 6)),
        "total_impulse": float(np.round(total_impulse, 3)),
        "average_thrust": float(np.round(thrust, 3)),
    }
