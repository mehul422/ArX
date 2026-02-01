from __future__ import annotations

from dataclasses import dataclass

from app.engine.openmotor_ai.ballistics import aggregate_metrics, simulate_ballistics
from app.engine.openmotor_ai.spec import MotorSpec, PropellantSpec, PropellantTab, NozzleSpec


@dataclass(frozen=True)
class TargetMetrics:
    total_impulse_ns: float
    burn_time_s: float
    average_pressure_psi: float
    peak_pressure_psi: float
    propellant_mass_lb: float
    delivered_isp_s: float


def _update_propellant(spec: MotorSpec, density_scale: float, burn_rate_scale: float) -> MotorSpec:
    tabs = [
        PropellantTab(
            a=tab.a * burn_rate_scale,
            n=tab.n,
            k=tab.k,
            m=tab.m,
            t=tab.t,
            min_pressure_pa=tab.min_pressure_pa,
            max_pressure_pa=tab.max_pressure_pa,
        )
        for tab in spec.propellant.tabs
    ]
    propellant = PropellantSpec(
        name=spec.propellant.name,
        density_kg_m3=spec.propellant.density_kg_m3 * density_scale,
        tabs=tabs,
    )
    return MotorSpec(
        config=spec.config,
        propellant=propellant,
        grains=spec.grains,
        nozzle=spec.nozzle,
    )


def _update_nozzle(spec: MotorSpec, efficiency_scale: float) -> MotorSpec:
    efficiency = max(0.1, min(1.0, spec.nozzle.efficiency * efficiency_scale))
    nozzle = NozzleSpec(
        throat_diameter_m=spec.nozzle.throat_diameter_m,
        exit_diameter_m=spec.nozzle.exit_diameter_m,
        throat_length_m=spec.nozzle.throat_length_m,
        conv_angle_deg=spec.nozzle.conv_angle_deg,
        div_angle_deg=spec.nozzle.div_angle_deg,
        efficiency=efficiency,
        erosion_coeff=spec.nozzle.erosion_coeff,
        slag_coeff=spec.nozzle.slag_coeff,
    )
    return MotorSpec(
        config=spec.config,
        propellant=spec.propellant,
        grains=spec.grains,
        nozzle=nozzle,
    )


def calibrate_to_targets(spec: MotorSpec, targets: TargetMetrics) -> MotorSpec:
    # First, scale density to match propellant mass
    metrics = aggregate_metrics(spec, simulate_ballistics(spec))
    current_mass_lb = metrics["propellant_mass"] * 2.20462262185 if metrics else 0.0
    density_scale = targets.propellant_mass_lb / max(current_mass_lb, 1e-6)
    current = _update_propellant(spec, density_scale, burn_rate_scale=1.0)

    # Grid search burn-rate scale to match pressure + burn time
    best = None
    for step in range(0, 61):
        scale = 0.2 + (3.0 - 0.2) * (step / 60.0)
        candidate = _update_propellant(current, density_scale=1.0, burn_rate_scale=scale)
        metrics = aggregate_metrics(candidate, simulate_ballistics(candidate))
        if not metrics:
            continue
        peak_pressure_psi = metrics["peak_chamber_pressure"] / 6894.757
        score = (
            abs(peak_pressure_psi - targets.peak_pressure_psi) / max(targets.peak_pressure_psi, 1e-6)
            + abs(metrics["burn_time"] - targets.burn_time_s) / max(targets.burn_time_s, 1e-6)
        )
        if best is None or score < best[0]:
            best = (score, candidate, metrics)

    if best is None:
        return current

    candidate, metrics = best[1], best[2]
    # Adjust nozzle efficiency to match total impulse
    efficiency_scale = targets.total_impulse_ns / max(metrics["total_impulse"], 1e-6)
    return _update_nozzle(candidate, efficiency_scale)
