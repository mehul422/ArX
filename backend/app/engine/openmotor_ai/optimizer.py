from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.engine.openmotor_ai.ballistics import aggregate_metrics, simulate_ballistics
from app.engine.openmotor_ai.constraints import DesignConstraints
from app.engine.openmotor_ai.ric_parser import RicData
from app.engine.openmotor_ai.spec import MotorSpec, spec_from_ric


@dataclass(frozen=True)
class OptimizedDesign:
    spec: MotorSpec
    metrics: dict[str, float]
    throat_diameter_m: float


def _with_throat(spec: MotorSpec, throat_diameter_m: float) -> MotorSpec:
    throat_scale = throat_diameter_m / max(spec.nozzle.throat_diameter_m, 1e-9)
    exit_diameter_m = spec.nozzle.exit_diameter_m * throat_scale
    return MotorSpec(
        config=spec.config,
        propellant=spec.propellant,
        grains=spec.grains,
        nozzle=spec.nozzle.__class__(
            throat_diameter_m=throat_diameter_m,
            exit_diameter_m=exit_diameter_m,
            throat_length_m=spec.nozzle.throat_length_m,
            conv_angle_deg=spec.nozzle.conv_angle_deg,
            div_angle_deg=spec.nozzle.div_angle_deg,
            efficiency=spec.nozzle.efficiency,
            erosion_coeff=spec.nozzle.erosion_coeff,
            slag_coeff=spec.nozzle.slag_coeff,
        ),
    )


def _with_core_scale(spec: MotorSpec, core_scale: float) -> MotorSpec:
    grains = [
        grain.__class__(
            diameter_m=grain.diameter_m,
            core_diameter_m=min(grain.diameter_m * 0.98, grain.core_diameter_m * core_scale),
            length_m=grain.length_m,
            inhibited_ends=grain.inhibited_ends,
        )
        for grain in spec.grains
    ]
    return MotorSpec(
        config=spec.config,
        propellant=spec.propellant,
        grains=grains,
        nozzle=spec.nozzle,
    )


def _with_length_scale(spec: MotorSpec, length_scale: float) -> MotorSpec:
    grains = [
        grain.__class__(
            diameter_m=grain.diameter_m,
            core_diameter_m=grain.core_diameter_m,
            length_m=grain.length_m * length_scale,
            inhibited_ends=grain.inhibited_ends,
        )
        for grain in spec.grains
    ]
    return MotorSpec(
        config=spec.config,
        propellant=spec.propellant,
        grains=grains,
        nozzle=spec.nozzle,
    )


def _with_diameter_scale(spec: MotorSpec, diameter_scale: float) -> MotorSpec:
    grains = [
        grain.__class__(
            diameter_m=grain.diameter_m * diameter_scale,
            core_diameter_m=grain.core_diameter_m * diameter_scale,
            length_m=grain.length_m,
            inhibited_ends=grain.inhibited_ends,
        )
        for grain in spec.grains
    ]
    return MotorSpec(
        config=spec.config,
        propellant=spec.propellant,
        grains=grains,
        nozzle=spec.nozzle,
    )


def _satisfies_constraints(metrics: dict[str, float], constraints: DesignConstraints) -> bool:
    peak_pressure_psi = metrics["peak_chamber_pressure"] / 6894.757
    port_throat = metrics["port_to_throat_ratio"]
    peak_mass_flux_lb_in2_s = metrics["peak_mass_flux"] * 0.00014503773773020923
    return (
        peak_pressure_psi <= constraints.max_pressure_psi
        and metrics["peak_kn"] <= constraints.max_kn
        and constraints.port_throat_min <= port_throat <= constraints.port_throat_max
        and peak_mass_flux_lb_in2_s <= constraints.max_mass_flux
    )


def _with_grain_count(spec: MotorSpec, count: int) -> MotorSpec:
    grains = spec.grains[: max(1, count)]
    return MotorSpec(
        config=spec.config,
        propellant=spec.propellant,
        grains=grains,
        nozzle=spec.nozzle,
    )


def optimize_throat(
    ric: RicData,
    constraints: DesignConstraints,
    throat_scale_min: float = 0.8,
    throat_scale_max: float = 1.6,
    core_scale_min: float = 1.0,
    core_scale_max: float = 1.8,
) -> OptimizedDesign:
    spec = spec_from_ric(ric)
    base_throat = spec.nozzle.throat_diameter_m
    max_grains = len(spec.grains)

    best: OptimizedDesign | None = None
    for grain_count in range(max_grains, 0, -1):
        grain_candidate = _with_grain_count(spec, grain_count)
        for core_step in range(0, 17):
            core_scale = core_scale_min + (core_scale_max - core_scale_min) * (core_step / 16.0)
            core_candidate = _with_core_scale(grain_candidate, core_scale)
            for step in range(0, 31):
                scale = throat_scale_min + (throat_scale_max - throat_scale_min) * (step / 30.0)
                candidate = _with_throat(core_candidate, base_throat * scale)
                try:
                    metrics = aggregate_metrics(candidate, simulate_ballistics(candidate))
                except Exception:
                    continue
                if not metrics:
                    continue
                if _satisfies_constraints(metrics, constraints):
                    best = OptimizedDesign(
                        spec=candidate,
                        metrics=metrics,
                        throat_diameter_m=candidate.nozzle.throat_diameter_m,
                    )
                    break
            if best:
                break
        if best:
            break

    if best is None:
        # fallback to lowest pressure candidate
        lowest = None
        for grain_count in range(max_grains, 0, -1):
            grain_candidate = _with_grain_count(spec, grain_count)
            for core_step in range(0, 17):
                core_scale = core_scale_min + (core_scale_max - core_scale_min) * (core_step / 16.0)
                core_candidate = _with_core_scale(grain_candidate, core_scale)
                for step in range(0, 31):
                    scale = throat_scale_min + (throat_scale_max - throat_scale_min) * (step / 30.0)
                    candidate = _with_throat(core_candidate, base_throat * scale)
                    try:
                        metrics = aggregate_metrics(candidate, simulate_ballistics(candidate))
                    except Exception:
                        continue
                    if not metrics:
                        continue
                    peak_pressure = metrics["peak_chamber_pressure"]
                    if lowest is None or peak_pressure < lowest[0]:
                        lowest = (peak_pressure, candidate, metrics)
        if lowest:
            _, candidate, metrics = lowest
            best = OptimizedDesign(
                spec=candidate, metrics=metrics, throat_diameter_m=candidate.nozzle.throat_diameter_m
            )

    if best is None:
        raise RuntimeError("Unable to optimize throat for constraints")
    return best


def optimize_for_impulse(
    ric: RicData,
    constraints: DesignConstraints,
    throat_scale_min: float = 0.8,
    throat_scale_max: float = 2.4,
    core_scale_min: float = 0.3,
    core_scale_max: float = 1.6,
) -> OptimizedDesign:
    spec = spec_from_ric(ric)
    base_throat = spec.nozzle.throat_diameter_m
    max_grains = len(spec.grains)

    best: OptimizedDesign | None = None
    for grain_count in range(max_grains, 0, -1):
        grain_candidate = _with_grain_count(spec, grain_count)
        for core_step in range(0, 25):
            core_scale = core_scale_min + (core_scale_max - core_scale_min) * (core_step / 24.0)
            core_candidate = _with_core_scale(grain_candidate, core_scale)
            for step in range(0, 41):
                scale = throat_scale_min + (throat_scale_max - throat_scale_min) * (step / 40.0)
                candidate = _with_throat(core_candidate, base_throat * scale)
                try:
                    metrics = aggregate_metrics(candidate, simulate_ballistics(candidate))
                except Exception:
                    continue
                if not metrics:
                    continue
                if not _satisfies_constraints(metrics, constraints):
                    continue
                impulse = metrics["total_impulse"]
                if best is None or impulse > best.metrics["total_impulse"]:
                    best = OptimizedDesign(
                        spec=candidate,
                        metrics=metrics,
                        throat_diameter_m=candidate.nozzle.throat_diameter_m,
                    )

    if best is None:
        raise RuntimeError("No design meets constraints for impulse optimization")
    return best


def optimize_for_target_impulse(
    ric: RicData,
    constraints: DesignConstraints,
    target_impulse_ns: float,
    throat_scale_min: float = 0.8,
    throat_scale_max: float = 2.4,
    core_scale_min: float = 0.3,
    core_scale_max: float = 1.6,
    length_scale_min: float = 0.5,
    length_scale_max: float = 2.0,
    throat_steps: int = 31,
    core_steps: int = 17,
    length_steps: int = 13,
    fixed_grain_count: int | None = None,
    diameter_scale_min: float = 1.0,
    diameter_scale_max: float = 1.0,
    diameter_steps: int = 1,
) -> OptimizedDesign:
    spec = spec_from_ric(ric)
    base_throat = spec.nozzle.throat_diameter_m
    max_grains = len(spec.grains)

    best: OptimizedDesign | None = None
    grain_counts = [fixed_grain_count] if fixed_grain_count else range(max_grains, 0, -1)
    diameter_steps = max(diameter_steps, 1)
    for diameter_step in range(0, diameter_steps):
        diameter_scale = diameter_scale_min + (diameter_scale_max - diameter_scale_min) * (
            diameter_step / max(diameter_steps - 1, 1)
        )
        diameter_candidate = _with_diameter_scale(spec, diameter_scale)
        for grain_count in grain_counts:
            if grain_count is None or grain_count <= 0 or grain_count > max_grains:
                continue
            grain_candidate = _with_grain_count(diameter_candidate, grain_count)
            length_steps = max(length_steps, 1)
            for length_step in range(0, length_steps):
                length_scale = length_scale_min + (length_scale_max - length_scale_min) * (
                    length_step / max(length_steps - 1, 1)
                )
                length_candidate = _with_length_scale(grain_candidate, length_scale)
                core_steps = max(core_steps, 1)
                for core_step in range(0, core_steps):
                    core_scale = core_scale_min + (core_scale_max - core_scale_min) * (
                        core_step / max(core_steps - 1, 1)
                    )
                    core_candidate = _with_core_scale(length_candidate, core_scale)
                    throat_steps = max(throat_steps, 1)
                    for step in range(0, throat_steps):
                        scale = throat_scale_min + (throat_scale_max - throat_scale_min) * (
                            step / max(throat_steps - 1, 1)
                        )
                        candidate = _with_throat(core_candidate, base_throat * scale)
                        try:
                            metrics = aggregate_metrics(candidate, simulate_ballistics(candidate))
                        except Exception:
                            continue
                        if not metrics:
                            continue
                        if not _satisfies_constraints(metrics, constraints):
                            continue
                        impulse = metrics["total_impulse"]
                        score = abs(impulse - target_impulse_ns)
                        if best is None or score < abs(best.metrics["total_impulse"] - target_impulse_ns):
                            best = OptimizedDesign(
                                spec=candidate,
                                metrics=metrics,
                                throat_diameter_m=candidate.nozzle.throat_diameter_m,
                            )

    if best is None:
        raise RuntimeError("No design meets constraints for target impulse")
    return best
