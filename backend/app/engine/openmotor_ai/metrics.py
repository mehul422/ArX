from __future__ import annotations

from dataclasses import dataclass

from app.engine.openmotor_ai.eng_parser import EngData
from app.engine.openmotor_ai.ric_parser import RicData
from app.engine.openmotor_ai.targets import TARGET_METRICS


@dataclass(frozen=True)
class BasicMetrics:
    burn_time_s: float
    total_impulse_ns: float
    average_thrust_n: float
    propellant_mass_kg: float
    propellant_length_m: float


def _integrate_trapezoid(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for idx in range(1, len(points)):
        t0, f0 = points[idx - 1]
        t1, f1 = points[idx]
        total += (t1 - t0) * (f0 + f1) * 0.5
    return total


def _propellant_volume_m3(ric: RicData) -> float:
    volume = 0.0
    for grain in ric.grains:
        props = grain.get("properties", {})
        diameter = float(props.get("diameter", 0.0))
        core_diameter = float(props.get("coreDiameter", 0.0))
        length = float(props.get("length", 0.0))
        outer_radius = diameter / 2.0
        inner_radius = core_diameter / 2.0
        volume += (3.141592653589793 * (outer_radius**2 - inner_radius**2) * length)
    return volume


def compute_basic_metrics(ric: RicData, eng: EngData) -> BasicMetrics:
    burn_time = eng.curve[-1][0]
    total_impulse = _integrate_trapezoid(eng.curve)
    average_thrust = total_impulse / burn_time if burn_time > 0 else 0.0
    propellant_volume = _propellant_volume_m3(ric)
    propellant_density = float(ric.propellant.get("density", 0.0))
    propellant_mass = propellant_volume * propellant_density
    propellant_length = sum(
        float(grain.get("properties", {}).get("length", 0.0)) for grain in ric.grains
    )
    return BasicMetrics(
        burn_time_s=burn_time,
        total_impulse_ns=total_impulse,
        average_thrust_n=average_thrust,
        propellant_mass_kg=propellant_mass,
        propellant_length_m=propellant_length,
    )


def metric_skeleton() -> dict[str, float | None]:
    return {name: None for name in TARGET_METRICS}
