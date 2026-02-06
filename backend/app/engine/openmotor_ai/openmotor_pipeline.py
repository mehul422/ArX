from __future__ import annotations

from dataclasses import dataclass, asdict
import re
from pathlib import Path
from typing import Iterable

from app.engine.openmotor_ai.eng_builder import build_eng
from app.engine.openmotor_ai.eng_export import export_eng
from app.engine.openmotor_ai.motorlib_adapter import (
    metrics_from_simresult,
    simulate_motorlib_with_result,
)
from app.engine.openmotor_ai.propellant_library import load_preset_propellants
from app.engine.openmotor_ai.propellant_schema import PropellantSchema, propellant_to_spec
from app.engine.openmotor_ai.ric_parser import RicData, load_ric
from app.engine.openmotor_ai.ric_writer import build_ric
from app.engine.openmotor_ai.spec import (
    BATESGrain,
    MotorConfig,
    MotorSpec,
    NozzleSpec,
    PropellantSpec,
    spec_from_ric,
)
from app.engine.openmotor_ai.scoring import Candidate, ScoreWeights, score_candidates
from app.engine.openmotor_ai.trajectory import (
    simulate_single_stage_apogee_params,
    simulate_two_stage_apogee,
    simulate_two_stage_apogee_params,
)


@dataclass(frozen=True)
class StageSearchConfig:
    diameter_scales: list[float]
    length_scales: list[float]
    core_scales: list[float]
    throat_scales: list[float]
    exit_scales: list[float]
    grain_count: int | None = None


@dataclass(frozen=True)
class TwoStageConstraints:
    max_pressure_psi: float
    max_kn: float
    max_vehicle_length_in: float
    max_stage_length_ratio: float = 1.15


@dataclass(frozen=True)
class TrajectoryTargets:
    apogee_ft: float
    max_velocity_m_s: float | None = None
    tolerance_pct: float = 0.02


@dataclass(frozen=True)
class VehicleParams:
    ref_diameter_m: float
    rocket_length_in: float


@dataclass(frozen=True)
class StageScales:
    diameter_scale: float
    length_scale: float
    core_scale: float
    throat_scale: float
    exit_scale: float


@dataclass(frozen=True)
class StageResult:
    spec: MotorSpec
    metrics: dict[str, float]
    log: dict[str, float]
    scales: StageScales | None = None


_FAST_TARGET_ONLY_PROPELLANTS = [
    "AP/Al/HTPB",
    "AP/HTPB",
    "APCP",
    "Double-base",
]


def _apply_scales(
    base: MotorSpec,
    diameter_scale: float,
    length_scale: float,
    core_scale: float,
    throat_scale: float,
    exit_scale: float,
    grain_count: int | None,
) -> MotorSpec:
    grains = base.grains[: grain_count] if grain_count else base.grains
    scaled_grains = []
    for grain in grains:
        diameter = grain.diameter_m * diameter_scale
        core = min(diameter * 0.98, grain.core_diameter_m * diameter_scale * core_scale)
        scaled_grains.append(
            grain.__class__(
                diameter_m=diameter,
                core_diameter_m=core,
                length_m=grain.length_m * length_scale,
                inhibited_ends=grain.inhibited_ends,
            )
        )
    throat = base.nozzle.throat_diameter_m * throat_scale
    exit_diameter = max(throat, base.nozzle.exit_diameter_m * exit_scale * throat_scale)
    nozzle = base.nozzle.__class__(
        throat_diameter_m=throat,
        exit_diameter_m=exit_diameter,
        throat_length_m=base.nozzle.throat_length_m,
        conv_angle_deg=base.nozzle.conv_angle_deg,
        div_angle_deg=base.nozzle.div_angle_deg,
        efficiency=base.nozzle.efficiency,
        erosion_coeff=base.nozzle.erosion_coeff,
        slag_coeff=base.nozzle.slag_coeff,
    )
    return MotorSpec(
        config=base.config,
        propellant=base.propellant,
        grains=scaled_grains,
        nozzle=nozzle,
    )


def _metrics_with_units(metrics: dict[str, float]) -> dict[str, float]:
    out = dict(metrics)
    out["peak_pressure_psi"] = metrics["peak_chamber_pressure"] / 6894.757
    out["average_pressure_psi"] = metrics["average_chamber_pressure"] / 6894.757
    out["peak_mass_flux_lb_in2_s"] = metrics["peak_mass_flux"] * 0.00014503773773020923
    return out


def _stage_length_in(spec: MotorSpec) -> float:
    return sum(grain.length_m for grain in spec.grains) * 39.3701


def _stage_diameter_in(spec: MotorSpec) -> float:
    return max(grain.diameter_m for grain in spec.grains) * 39.3701


def _satisfies_constraints(metrics: dict[str, float], constraints: TwoStageConstraints) -> bool:
    peak_pressure_psi = metrics["peak_chamber_pressure"] / 6894.757
    return peak_pressure_psi <= constraints.max_pressure_psi and metrics["peak_kn"] <= constraints.max_kn


def _search_stage(
    base: MotorSpec,
    target_impulse_ns: float,
    search: StageSearchConfig,
    constraints: TwoStageConstraints,
    fixed_diameter_scale: float | None = None,
    reject_log: list[dict[str, str]] | None = None,
    reject_context: dict[str, str] | None = None,
) -> StageResult | None:
    best: StageResult | None = None
    diameter_scales = (
        [fixed_diameter_scale] if fixed_diameter_scale is not None else search.diameter_scales
    )
    for diameter_scale in diameter_scales:
        for length_scale in search.length_scales:
            for core_scale in search.core_scales:
                for throat_scale in search.throat_scales:
                    for exit_scale in search.exit_scales:
                        spec = _apply_scales(
                            base=base,
                            diameter_scale=diameter_scale,
                            length_scale=length_scale,
                            core_scale=core_scale,
                            throat_scale=throat_scale,
                            exit_scale=exit_scale,
                            grain_count=search.grain_count,
                        )
                        spec = _normalize_spec_for_motorlib(spec)
                        try:
                            spec, steps, metrics, engine = _simulate_with_fallback(spec)
                        except Exception as exc:
                            if reject_log is not None:
                                reject_log.append(
                                    {
                                        **(reject_context or {}),
                                        "reason": "simulation_failed",
                                        "detail": str(exc),
                                    }
                                )
                            continue
                        if not steps:
                            continue
                        if not _satisfies_constraints(metrics, constraints):
                            continue
                        score = abs(metrics["total_impulse"] - target_impulse_ns)
                        if best is None or score < abs(best.metrics["total_impulse"] - target_impulse_ns):
                            best = StageResult(
                                spec=spec,
                                metrics=metrics | {"simulation_engine": engine},
                                log=_metrics_with_units(metrics),
                            )
    return best


def _float_key(value: float, places: int = 6) -> float:
    return round(float(value), places)


def _base_spec_cache_key(base: MotorSpec) -> tuple[object, ...]:
    grains_key = tuple(
        (
            _float_key(grain.diameter_m),
            _float_key(grain.core_diameter_m),
            _float_key(grain.length_m),
            grain.inhibited_ends,
        )
        for grain in base.grains
    )
    nozzle = base.nozzle
    nozzle_key = (
        _float_key(nozzle.throat_diameter_m),
        _float_key(nozzle.exit_diameter_m),
        _float_key(nozzle.throat_length_m),
        _float_key(nozzle.conv_angle_deg),
        _float_key(nozzle.div_angle_deg),
    )
    return (base.propellant.name, grains_key, nozzle_key)


def _build_stage_grid(
    base: MotorSpec,
    search: StageSearchConfig,
    constraints: TwoStageConstraints,
    reject_log: list[dict[str, str]] | None = None,
    reject_context: dict[str, str] | None = None,
    cache: dict[tuple[object, ...], StageResult | None] | None = None,
) -> list[StageResult]:
    results: list[StageResult] = []
    cache = cache if cache is not None else {}
    base_key = _base_spec_cache_key(base)
    for diameter_scale in search.diameter_scales:
        for length_scale in search.length_scales:
            for core_scale in search.core_scales:
                for throat_scale in search.throat_scales:
                    for exit_scale in search.exit_scales:
                        cache_key = (
                            base_key,
                            _float_key(diameter_scale),
                            _float_key(length_scale),
                            _float_key(core_scale),
                            _float_key(throat_scale),
                            _float_key(exit_scale),
                            search.grain_count,
                        )
                        cached = cache.get(cache_key)
                        if cached is not None or cache_key in cache:
                            if cached is not None:
                                results.append(cached)
                            continue
                        spec = _apply_scales(
                            base=base,
                            diameter_scale=diameter_scale,
                            length_scale=length_scale,
                            core_scale=core_scale,
                            throat_scale=throat_scale,
                            exit_scale=exit_scale,
                            grain_count=search.grain_count,
                        )
                        spec = _normalize_spec_for_motorlib(spec)
                        try:
                            spec, steps, metrics, engine = _simulate_with_fallback(spec)
                        except Exception as exc:
                            cache[cache_key] = None
                            if reject_log is not None:
                                reject_log.append(
                                    {
                                        **(reject_context or {}),
                                        "reason": "simulation_failed",
                                        "detail": str(exc),
                                    }
                                )
                            continue
                        if not steps:
                            cache[cache_key] = None
                            continue
                        if not _satisfies_constraints(metrics, constraints):
                            cache[cache_key] = None
                            continue
                        stage = StageResult(
                            spec=spec,
                            metrics=metrics | {"simulation_engine": engine},
                            log=_metrics_with_units(metrics),
                            scales=StageScales(
                                diameter_scale=diameter_scale,
                                length_scale=length_scale,
                                core_scale=core_scale,
                                throat_scale=throat_scale,
                                exit_scale=exit_scale,
                            ),
                        )
                        cache[cache_key] = stage
                        results.append(stage)
    return results


def _group_grid_by_diameter(grid: list[StageResult]) -> dict[float, list[StageResult]]:
    grouped: dict[float, list[StageResult]] = {}
    for stage in grid:
        if not stage.scales:
            continue
        key = _float_key(stage.scales.diameter_scale)
        grouped.setdefault(key, []).append(stage)
    return grouped


def _select_best_stage_for_target(
    grid: list[StageResult],
    target_impulse_ns: float,
) -> StageResult | None:
    if not grid:
        return None
    best = None
    best_score = None
    for stage in grid:
        score = abs(stage.metrics["total_impulse"] - target_impulse_ns)
        if best_score is None or score < best_score:
            best_score = score
            best = stage
    return best


def _refine_values(center: float, min_value: float, max_value: float, spread: float) -> list[float]:
    deltas = [-spread, -spread / 2.0, 0.0, spread / 2.0, spread]
    values = []
    for delta in deltas:
        value = center * (1.0 + delta)
        value = max(min_value, min(max_value, value))
        values.append(_float_key(value, places=4))
    return sorted(set(values))


def _refine_search_config(
    search: StageSearchConfig,
    scales: StageScales,
    *,
    fixed_diameter: float | None = None,
    spread: float = 0.06,
) -> StageSearchConfig:
    diameter_min = min(search.diameter_scales)
    diameter_max = max(search.diameter_scales)
    length_min = min(search.length_scales)
    length_max = max(search.length_scales)
    core_min = min(search.core_scales)
    core_max = max(search.core_scales)
    throat_min = min(search.throat_scales)
    throat_max = max(search.throat_scales)
    exit_min = min(search.exit_scales)
    exit_max = max(search.exit_scales)
    if fixed_diameter is None:
        diameter_scales = _refine_values(scales.diameter_scale, diameter_min, diameter_max, spread)
    else:
        diameter_scales = [_float_key(fixed_diameter)]
    return StageSearchConfig(
        diameter_scales=diameter_scales,
        length_scales=_refine_values(scales.length_scale, length_min, length_max, spread),
        core_scales=_refine_values(scales.core_scale, core_min, core_max, spread),
        throat_scales=_refine_values(scales.throat_scale, throat_min, throat_max, spread),
        exit_scales=_refine_values(scales.exit_scale, exit_min, exit_max, spread),
        grain_count=search.grain_count,
    )


def _refine_split_ratios(split: float) -> list[float]:
    steps = [-0.1, -0.05, 0.0, 0.05, 0.1]
    refined = []
    for step in steps:
        value = split + step
        value = max(0.2, min(0.8, value))
        refined.append(_float_key(value, places=3))
    return sorted(set(refined))


def generate_two_stage_designs(
    base_ric_path: str,
    output_dir: str,
    total_target_impulse_ns: float,
    split_ratio: float,
    constraints: TwoStageConstraints,
    search: StageSearchConfig,
    rkt_path: str | None = None,
    cd_max: float = 0.5,
    mach_max: float = 2.0,
    cd_ramp: bool = False,
    total_mass_kg: float | None = None,
    separation_delay_s: float = 0.0,
    ignition_delay_s: float = 0.0,
    propellant_options: list[PropellantSpec] | None = None,
    artifact_prefix: str = "openmotor_ai_60000",
) -> dict[str, dict[str, float]]:
    ric: RicData = load_ric(base_ric_path)
    base = _normalize_spec_for_motorlib(spec_from_ric(ric))
    propellants = propellant_options or [base.propellant]

    stage0_target = total_target_impulse_ns * split_ratio
    stage1_target = total_target_impulse_ns * (1.0 - split_ratio)

    best_pair: tuple[StageResult, StageResult] | None = None
    best_score = None
    best_propellant: PropellantSpec | None = None
    for propellant in propellants:
        prop_base = MotorSpec(
            config=base.config,
            propellant=propellant,
            grains=base.grains,
            nozzle=base.nozzle,
        )
        for diameter_scale in search.diameter_scales:
            stage0 = _search_stage(
                prop_base,
                stage0_target,
                search,
                constraints,
                fixed_diameter_scale=diameter_scale,
            )
            stage1 = _search_stage(
                prop_base,
                stage1_target,
                search,
                constraints,
                fixed_diameter_scale=diameter_scale,
            )
            if stage0 is None or stage1 is None:
                continue
            score = abs(stage0.metrics["total_impulse"] - stage0_target) + abs(
                stage1.metrics["total_impulse"] - stage1_target
            )
            if best_score is None or score < best_score:
                best_score = score
                best_pair = (stage0, stage1)
                best_propellant = propellant

    if best_pair is None:
        raise RuntimeError("No feasible stage design found with current constraints/ranges.")

    stage0, stage1 = best_pair

    stage0_len = _stage_length_in(stage0.spec)
    stage1_len = _stage_length_in(stage1.spec)
    if stage0_len + stage1_len > constraints.max_vehicle_length_in:
        raise RuntimeError("Motor stack exceeds vehicle length constraint.")
    length_ratio = max(stage0_len, stage1_len) / max(min(stage0_len, stage1_len), 1e-6)
    if length_ratio > constraints.max_stage_length_ratio:
        raise RuntimeError("Stage lengths differ too much for two-stage packaging.")
    if abs(_stage_diameter_in(stage0.spec) - _stage_diameter_in(stage1.spec)) > 1e-6:
        raise RuntimeError("Stage diameters differ; must be identical.")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for idx, stage in enumerate([stage0, stage1]):
        steps, _ = simulate_motorlib_with_result(stage.spec)
        eng = build_eng(
            stage.spec,
            steps,
            designation=f"{artifact_prefix}-S{idx}",
            manufacturer="openmotor-ai",
        )
        (out_dir / f"{artifact_prefix}_stage{idx}.ric").write_text(
            build_ric(stage.spec), encoding="utf-8"
        )
        (out_dir / f"{artifact_prefix}_stage{idx}.eng").write_text(export_eng(eng), encoding="utf-8")

    apogee = None
    if rkt_path:
        apogee = simulate_two_stage_apogee(
            stage0=stage0.spec,
            stage1=stage1.spec,
            rkt_path=rkt_path,
            cd_max=cd_max,
            mach_max=mach_max,
            cd_ramp=cd_ramp,
            total_mass_kg=total_mass_kg,
            separation_delay_s=separation_delay_s,
            ignition_delay_s=ignition_delay_s,
        )

    log = {
        "stage0": stage0.log | {"stage_length_in": stage0_len, "stage_diameter_in": _stage_diameter_in(stage0.spec)},
        "stage1": stage1.log | {"stage_length_in": stage1_len, "stage_diameter_in": _stage_diameter_in(stage1.spec)},
        "targets": {
            "total_target_impulse_ns": total_target_impulse_ns,
            "stage0_target_impulse_ns": stage0_target,
            "stage1_target_impulse_ns": stage1_target,
            "split_ratio": split_ratio,
        },
        "constraints": asdict(constraints),
        "search": asdict(search),
    }
    if best_propellant:
        log["propellant"] = {
            "name": best_propellant.name,
            "density_kg_m3": best_propellant.density_kg_m3,
        }
    if apogee:
        log["apogee"] = {
            "apogee_m": apogee.apogee_m,
            "apogee_ft": apogee.apogee_m * 3.28084,
            "max_velocity_m_s": apogee.max_velocity_m_s,
            "max_accel_m_s2": apogee.max_accel_m_s2,
            "burnout_time_s": apogee.burnout_time_s,
            "cd_max": cd_max,
            "mach_max": mach_max,
            "cd_ramp": cd_ramp,
            "total_mass_kg": total_mass_kg,
            "separation_delay_s": separation_delay_s,
            "ignition_delay_s": ignition_delay_s,
        }
    (out_dir / f"{artifact_prefix}_metrics.json").write_text(
        __import__("json").dumps(log, indent=2),
        encoding="utf-8",
    )
    return log


def generate_single_stage_designs(
    base_ric_path: str,
    output_dir: str,
    total_target_impulse_ns: float,
    constraints: TwoStageConstraints,
    search: StageSearchConfig,
    cd_max: float = 0.5,
    mach_max: float = 2.0,
    cd_ramp: bool = False,
    total_mass_kg: float | None = None,
    ref_diameter_m: float | None = None,
    propellant_options: list[PropellantSpec] | None = None,
    artifact_prefix: str = "openmotor_ai_60000",
) -> dict[str, dict[str, float]]:
    ric: RicData = load_ric(base_ric_path)
    base = _normalize_spec_for_motorlib(spec_from_ric(ric))
    propellants = propellant_options or [base.propellant]

    best: StageResult | None = None
    best_score = None
    best_propellant: PropellantSpec | None = None
    for propellant in propellants:
        prop_base = MotorSpec(
            config=base.config,
            propellant=propellant,
            grains=base.grains,
            nozzle=base.nozzle,
        )
        for diameter_scale in search.diameter_scales:
            stage = _search_stage(
                prop_base,
                total_target_impulse_ns,
                search,
                constraints,
                fixed_diameter_scale=diameter_scale,
            )
            if stage is None:
                continue
            score = abs(stage.metrics["total_impulse"] - total_target_impulse_ns)
            if best_score is None or score < best_score:
                best_score = score
                best = stage
                best_propellant = propellant

    if best is None:
        raise RuntimeError("No feasible stage design found with current constraints/ranges.")

    stage_len = _stage_length_in(best.spec)
    if stage_len > constraints.max_vehicle_length_in:
        raise RuntimeError("Motor length exceeds vehicle length constraint.")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    steps, _ = simulate_motorlib_with_result(best.spec)
    eng = build_eng(best.spec, steps, designation=artifact_prefix, manufacturer="openmotor-ai")
    ric_out = out_dir / f"{artifact_prefix}.ric"
    eng_out = out_dir / f"{artifact_prefix}.eng"
    ric_out.write_text(build_ric(best.spec), encoding="utf-8")
    eng_out.write_text(export_eng(eng), encoding="utf-8")

    apogee = None
    if ref_diameter_m is not None and total_mass_kg is not None:
        apogee = simulate_single_stage_apogee_params(
            stage=best.spec,
            ref_diameter_m=ref_diameter_m,
            total_mass_kg=total_mass_kg,
            cd_max=cd_max,
            mach_max=mach_max,
            cd_ramp=cd_ramp,
            launch_altitude_m=0.0,
            wind_speed_m_s=0.0,
            temperature_k=None,
        )

    log = {
        "stage": best.log | {"stage_length_in": stage_len, "stage_diameter_in": _stage_diameter_in(best.spec)},
        "targets": {"total_target_impulse_ns": total_target_impulse_ns},
        "constraints": asdict(constraints),
        "search": asdict(search),
    }
    if best_propellant:
        log["propellant"] = {
            "name": best_propellant.name,
            "density_kg_m3": best_propellant.density_kg_m3,
        }
    if apogee:
        log["apogee"] = {
            "apogee_m": apogee.apogee_m,
            "apogee_ft": apogee.apogee_m * 3.28084,
            "max_velocity_m_s": apogee.max_velocity_m_s,
            "max_accel_m_s2": apogee.max_accel_m_s2,
            "burnout_time_s": apogee.burnout_time_s,
            "cd_max": cd_max,
            "mach_max": mach_max,
            "cd_ramp": cd_ramp,
            "total_mass_kg": total_mass_kg,
        }
    (out_dir / f"{artifact_prefix}_metrics.json").write_text(
        __import__("json").dumps(log, indent=2),
        encoding="utf-8",
    )
    return log


def _combine_stage_metrics(
    stage0: StageResult,
    stage1: StageResult,
    constraints: TwoStageConstraints,
) -> dict[str, float]:
    m0 = stage0.metrics
    m1 = stage1.metrics
    total_impulse = m0["total_impulse"] + m1["total_impulse"]
    burn_time = m0["burn_time"] + m1["burn_time"]
    avg_thrust = total_impulse / max(burn_time, 1e-6)
    avg_pressure = (
        m0["average_chamber_pressure"] * m0["burn_time"]
        + m1["average_chamber_pressure"] * m1["burn_time"]
    ) / max(burn_time, 1e-6)
    delivered_isp = (
        m0["delivered_specific_impulse"] * m0["total_impulse"]
        + m1["delivered_specific_impulse"] * m1["total_impulse"]
    ) / max(total_impulse, 1e-6)
    ideal_cf = (
        m0["ideal_thrust_coefficient"] * m0["total_impulse"]
        + m1["ideal_thrust_coefficient"] * m1["total_impulse"]
    ) / max(total_impulse, 1e-6)
    delivered_cf = (
        m0["delivered_thrust_coefficient"] * m0["total_impulse"]
        + m1["delivered_thrust_coefficient"] * m1["total_impulse"]
    ) / max(total_impulse, 1e-6)
    port_throat = min(m0.get("port_to_throat_ratio", 0.0), m1.get("port_to_throat_ratio", 0.0))
    volume_loading = (m0.get("volume_loading", 0.0) + m1.get("volume_loading", 0.0)) / 2.0

    return {
        "burn_time": burn_time,
        "total_impulse": total_impulse,
        "average_thrust": avg_thrust,
        "average_chamber_pressure": avg_pressure,
        "peak_chamber_pressure": max(m0["peak_chamber_pressure"], m1["peak_chamber_pressure"]),
        "initial_kn": max(m0["initial_kn"], m1["initial_kn"]),
        "peak_kn": max(m0["peak_kn"], m1["peak_kn"]),
        "ideal_thrust_coefficient": ideal_cf,
        "delivered_thrust_coefficient": delivered_cf,
        "delivered_specific_impulse": delivered_isp,
        "propellant_mass": m0["propellant_mass"] + m1["propellant_mass"],
        "propellant_length": m0["propellant_length"] + m1["propellant_length"],
        "port_to_throat_ratio": port_throat,
        "volume_loading": volume_loading,
        "peak_mass_flux": max(m0["peak_mass_flux"], m1["peak_mass_flux"]),
        "max_pressure": constraints.max_pressure_psi * 6894.757,
        "max_kn": constraints.max_kn,
    }


def _build_thrust_curve(
    stage0: StageResult,
    stage1: StageResult,
    separation_delay_s: float,
    ignition_delay_s: float,
) -> list[tuple[float, float]]:
    curve: list[tuple[float, float]] = []
    steps0, _ = simulate_motorlib_with_result(stage0.spec)
    steps1, _ = simulate_motorlib_with_result(stage1.spec)
    for step in steps0:
        curve.append((step.time_s, step.thrust_n))
    offset = (steps0[-1].time_s if steps0 else 0.0) + separation_delay_s + ignition_delay_s
    if separation_delay_s + ignition_delay_s > 0.0:
        curve.append((offset, 0.0))
    for step in steps1:
        curve.append((step.time_s + offset, step.thrust_n))
    return curve


def _build_single_stage_thrust_curve(stage: StageResult) -> list[tuple[float, float]]:
    curve: list[tuple[float, float]] = []
    steps, _ = simulate_motorlib_with_result(stage.spec)
    for step in steps:
        curve.append((step.time_s, step.thrust_n))
    return curve


def _single_stage_metrics(stage: StageResult, constraints: TwoStageConstraints) -> dict[str, float]:
    metrics = dict(stage.metrics)
    metrics["max_pressure"] = constraints.max_pressure_psi * 6894.757
    metrics["max_kn"] = constraints.max_kn
    return metrics


def _filter_propellants(
    presets: list[PropellantSchema],
    allowed_families: list[str] | None,
    allowed_names: list[str] | None,
) -> list[PropellantSchema]:
    if not allowed_families and not allowed_names:
        return presets
    families = {name.strip().lower() for name in (allowed_families or [])}
    names = {name.strip().lower() for name in (allowed_names or [])}
    selected: list[PropellantSchema] = []
    for prop in presets:
        family = (prop.family or "").lower()
        name = prop.name.lower()
        if families and family in families:
            selected.append(prop)
            continue
        if names and name in names:
            selected.append(prop)
            continue
    return selected


def _objective_reports(
    apogee_ft: float | None,
    max_velocity_m_s: float | None,
    target_apogee_ft: float | None,
    target_max_velocity_m_s: float | None,
) -> list[dict[str, float | str]]:
    reports: list[dict[str, float | str]] = []
    if target_apogee_ft is not None and apogee_ft is not None:
        reports.append(
            {
                "name": "apogee_ft",
                "target": target_apogee_ft,
                "predicted": apogee_ft,
                "error_pct": abs(apogee_ft - target_apogee_ft) / max(target_apogee_ft, 1e-6) * 100.0,
                "units": "ft",
            }
        )
    if target_max_velocity_m_s is not None and max_velocity_m_s is not None:
        reports.append(
            {
                "name": "max_velocity_m_s",
                "target": target_max_velocity_m_s,
                "predicted": max_velocity_m_s,
                "error_pct": abs(max_velocity_m_s - target_max_velocity_m_s)
                / max(target_max_velocity_m_s, 1e-6)
                * 100.0,
                "units": "m/s",
            }
        )
    return reports


def _objective_error_pct(
    apogee_ft: float | None,
    max_velocity_m_s: float | None,
    target_apogee_ft: float | None,
    target_max_velocity_m_s: float | None,
) -> float | None:
    errors: list[float] = []
    if target_apogee_ft is not None and apogee_ft is not None:
        errors.append(abs(apogee_ft - target_apogee_ft) / max(target_apogee_ft, 1e-6))
    if target_max_velocity_m_s is not None and max_velocity_m_s is not None:
        errors.append(abs(max_velocity_m_s - target_max_velocity_m_s) / max(target_max_velocity_m_s, 1e-6))
    if not errors:
        return None
    return float(sum(errors) / len(errors))


def _objective_error_pct_max(
    apogee_ft: float | None,
    max_velocity_m_s: float | None,
    target_apogee_ft: float | None,
    target_max_velocity_m_s: float | None,
) -> float | None:
    errors: list[float] = []
    if target_apogee_ft is not None and apogee_ft is not None:
        if apogee_ft <= target_apogee_ft:
            errors.append((target_apogee_ft - apogee_ft) / max(target_apogee_ft, 1e-6))
        else:
            errors.append(
                1.0
                + (apogee_ft - target_apogee_ft) / max(target_apogee_ft, 1e-6)
            )
    if target_max_velocity_m_s is not None and max_velocity_m_s is not None:
        if max_velocity_m_s <= target_max_velocity_m_s:
            errors.append(
                (target_max_velocity_m_s - max_velocity_m_s)
                / max(target_max_velocity_m_s, 1e-6)
            )
        else:
            errors.append(
                1.0
                + (max_velocity_m_s - target_max_velocity_m_s)
                / max(target_max_velocity_m_s, 1e-6)
            )
    if not errors:
        return None
    return float(sum(errors) / len(errors))


def _within_max_targets(
    apogee_ft: float | None,
    max_velocity_m_s: float | None,
    target_apogee_ft: float | None,
    target_max_velocity_m_s: float | None,
) -> bool:
    if target_apogee_ft is not None and apogee_ft is not None and apogee_ft > target_apogee_ft:
        return False
    if (
        target_max_velocity_m_s is not None
        and max_velocity_m_s is not None
        and max_velocity_m_s > target_max_velocity_m_s
    ):
        return False
    return True


def _split_stage_dry_masses(
    total_mass_kg: float,
    prop0_kg: float,
    prop1_kg: float,
) -> tuple[float, float]:
    desired_dry = max(total_mass_kg - (prop0_kg + prop1_kg), 1e-6)
    prop_total = prop0_kg + prop1_kg
    if prop_total <= 0:
        return desired_dry / 2.0, desired_dry / 2.0
    ratio = prop0_kg / prop_total
    return desired_dry * ratio, desired_dry * (1.0 - ratio)


def estimate_total_impulse_ns_two_stage_params(
    base_spec0: MotorSpec,
    base_spec1: MotorSpec,
    ref_diameter_m: float,
    total_mass_kg: float,
    target_apogee_ft: float | None,
    max_velocity_m_s: float | None,
    cd_max: float,
    mach_max: float,
    cd_ramp: bool,
    separation_delay_s: float,
    ignition_delay_s: float,
    launch_altitude_m: float = 0.0,
    wind_speed_m_s: float = 0.0,
    temperature_k: float | None = None,
) -> float:
    base_spec0 = _normalize_spec_for_motorlib(base_spec0)
    base_spec1 = _normalize_spec_for_motorlib(base_spec1)
    try:
        base_spec0, _, metrics0, _ = _simulate_with_fallback(base_spec0)
    except Exception as exc:
        raise RuntimeError(f"Baseline stage0 simulation failed: {exc}") from exc
    try:
        base_spec1, _, metrics1, _ = _simulate_with_fallback(base_spec1)
    except Exception:
        base_spec1 = base_spec0
        metrics1 = metrics0

    prop0 = metrics0.get("propellant_mass", 0.0)
    prop1 = metrics1.get("propellant_mass", 0.0)
    stage0_dry, stage1_dry = _split_stage_dry_masses(total_mass_kg, prop0, prop1)

    apogee = simulate_two_stage_apogee_params(
        stage0=base_spec0,
        stage1=base_spec1,
        ref_diameter_m=ref_diameter_m,
        stage0_dry_kg=stage0_dry,
        stage1_dry_kg=stage1_dry,
        cd_max=cd_max,
        mach_max=mach_max,
        cd_ramp=cd_ramp,
        separation_delay_s=separation_delay_s,
        ignition_delay_s=ignition_delay_s,
        total_mass_kg=total_mass_kg,
        launch_altitude_m=launch_altitude_m,
        wind_speed_m_s=wind_speed_m_s,
        temperature_k=temperature_k,
    )

    base_total_impulse = metrics0["total_impulse"] + metrics1["total_impulse"]
    base_apogee_ft = max(apogee.apogee_m * 3.28084, 1e-6)
    base_max_v = max(apogee.max_velocity_m_s, 1e-6)

    if target_apogee_ft is None and max_velocity_m_s is None:
        return base_total_impulse
    if target_apogee_ft is None:
        scale = max_velocity_m_s / base_max_v
    elif max_velocity_m_s is None:
        scale_apogee = max(target_apogee_ft, 1.0) / base_apogee_ft
        scale = scale_apogee**0.5
    else:
        scale_apogee = max(target_apogee_ft, 1.0) / base_apogee_ft
        scale_from_apogee = scale_apogee**0.5
        scale_from_v = max_velocity_m_s / base_max_v
        scale = 0.7 * scale_from_apogee + 0.3 * scale_from_v

    scale = max(0.4, min(scale, 3.0))
    return base_total_impulse * scale


def _json_safe(value):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _slugify_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _normalize_spec_for_motorlib(spec: MotorSpec) -> MotorSpec:
    tabs = []
    for tab in spec.propellant.tabs:
        n = tab.n if tab.n > 0 else 0.01
        tabs.append(
            tab.__class__(
                a=tab.a,
                n=n,
                k=tab.k,
                m=tab.m,
                t=tab.t,
                min_pressure_pa=tab.min_pressure_pa,
                max_pressure_pa=tab.max_pressure_pa,
            )
        )
    propellant = spec.propellant.__class__(
        name=spec.propellant.name,
        density_kg_m3=spec.propellant.density_kg_m3,
        tabs=tabs,
    )
    grains = []
    for grain in spec.grains:
        diameter = max(grain.diameter_m, 0.0)
        core = max(min(grain.core_diameter_m, diameter * 0.98), 0.0)
        grains.append(
            grain.__class__(
                diameter_m=diameter,
                core_diameter_m=core,
                length_m=grain.length_m,
                inhibited_ends=grain.inhibited_ends,
            )
        )

    throat = max(spec.nozzle.throat_diameter_m, 1e-9)
    max_core = max((g.core_diameter_m for g in grains), default=0.0)
    min_port_throat = spec.config.min_port_throat_ratio
    if min_port_throat > 0.0 and max_core > 0.0:
        required_throat = max_core / (min_port_throat**0.5)
        throat = min(throat, required_throat)
    exit_diameter = max(spec.nozzle.exit_diameter_m, throat)
    nozzle = spec.nozzle.__class__(
        throat_diameter_m=throat,
        exit_diameter_m=exit_diameter,
        throat_length_m=spec.nozzle.throat_length_m,
        conv_angle_deg=spec.nozzle.conv_angle_deg,
        div_angle_deg=spec.nozzle.div_angle_deg,
        efficiency=spec.nozzle.efficiency,
        erosion_coeff=spec.nozzle.erosion_coeff,
        slag_coeff=spec.nozzle.slag_coeff,
    )

    port_throat = (max_core / throat) ** 2 if throat > 0 else 0.0
    min_port_throat = min(spec.config.min_port_throat_ratio, port_throat) if port_throat > 0 else 0.0
    config = spec.config.__class__(
        amb_pressure_pa=spec.config.amb_pressure_pa,
        burnout_thrust_threshold_n=spec.config.burnout_thrust_threshold_n,
        burnout_web_threshold_m=spec.config.burnout_web_threshold_m,
        map_dim=spec.config.map_dim,
        max_mass_flux_kg_m2_s=spec.config.max_mass_flux_kg_m2_s,
        max_pressure_pa=spec.config.max_pressure_pa,
        min_port_throat_ratio=min_port_throat,
        timestep_s=spec.config.timestep_s,
    )

    return MotorSpec(config=config, propellant=propellant, grains=grains, nozzle=nozzle)


def _try_simulate_with_throat_reduction(
    spec: MotorSpec,
    *,
    max_steps: int = 14,
    factor: float = 0.8,
    min_throat_ratio: float = 0.05,
) -> tuple[MotorSpec, list["TimeStep"], "SimulationResult"]:
    from app.engine.openmotor_ai.motorlib_adapter import simulate_motorlib_with_result

    last_exc: Exception | None = None
    current = spec
    original_throat = max(spec.nozzle.throat_diameter_m, 1e-9)
    base_min_thrust = spec.config.burnout_thrust_threshold_n
    for _ in range(max_steps):
        try:
            steps, sim = simulate_motorlib_with_result(current)
            return current, steps, sim
        except Exception as exc:
            last_exc = exc
            msg = str(exc)
            if "did not generate thrust" not in msg:
                break
        new_throat = current.nozzle.throat_diameter_m * factor
        if new_throat / original_throat < min_throat_ratio:
            break
        max_core = max((g.core_diameter_m for g in current.grains), default=0.0)
        port_throat = (max_core / new_throat) ** 2 if new_throat > 0 else 0.0
        adjusted_min_port_throat = min(current.config.min_port_throat_ratio, port_throat) if port_throat > 0 else 0.0
        lowered_thrust_threshold = min(base_min_thrust, 1e-6)
        current = current.__class__(
            config=current.config.__class__(
                amb_pressure_pa=current.config.amb_pressure_pa,
                burnout_thrust_threshold_n=lowered_thrust_threshold,
                burnout_web_threshold_m=current.config.burnout_web_threshold_m,
                map_dim=current.config.map_dim,
                max_mass_flux_kg_m2_s=current.config.max_mass_flux_kg_m2_s,
                max_pressure_pa=current.config.max_pressure_pa,
                min_port_throat_ratio=adjusted_min_port_throat,
                timestep_s=current.config.timestep_s,
            ),
            propellant=current.propellant,
            grains=current.grains,
            nozzle=current.nozzle.__class__(
                throat_diameter_m=new_throat,
                exit_diameter_m=max(current.nozzle.exit_diameter_m, new_throat),
                throat_length_m=current.nozzle.throat_length_m,
                conv_angle_deg=current.nozzle.conv_angle_deg,
                div_angle_deg=current.nozzle.div_angle_deg,
                efficiency=current.nozzle.efficiency,
                erosion_coeff=current.nozzle.erosion_coeff,
                slag_coeff=current.nozzle.slag_coeff,
            ),
        )
    raise last_exc or RuntimeError("Motor simulation failed after throat reduction attempts")


def _simulate_with_fallback(
    spec: MotorSpec,
) -> tuple[MotorSpec, list["TimeStep"], dict[str, float], str]:
    from app.engine.openmotor_ai.ballistics import _simulate_ballistics_internal, aggregate_metrics
    from app.engine.openmotor_ai.motorlib_adapter import metrics_from_simresult

    try:
        spec, steps, sim = _try_simulate_with_throat_reduction(spec)
        metrics = metrics_from_simresult(sim)
        return spec, steps, metrics, "motorlib"
    except Exception:
        relaxed = spec.__class__(
            config=spec.config.__class__(
                amb_pressure_pa=spec.config.amb_pressure_pa,
                burnout_thrust_threshold_n=0.0,
                burnout_web_threshold_m=spec.config.burnout_web_threshold_m,
                map_dim=spec.config.map_dim,
                max_mass_flux_kg_m2_s=spec.config.max_mass_flux_kg_m2_s,
                max_pressure_pa=spec.config.max_pressure_pa,
                min_port_throat_ratio=0.0,
                timestep_s=spec.config.timestep_s,
            ),
            propellant=spec.propellant,
            grains=spec.grains,
            nozzle=spec.nozzle,
        )
        steps = _simulate_ballistics_internal(relaxed)
        if not steps:
            raise
        metrics = aggregate_metrics(relaxed, steps)
        burn_time = metrics.get("burn_time", 0.0)
        if burn_time > 0:
            metrics["average_thrust"] = metrics.get("total_impulse", 0.0) / burn_time
        return relaxed, steps, metrics, "internal_fallback"


def run_as_is_two_stage(
    stage0_ric_path: str,
    stage1_ric_path: str,
    rkt_path: str,
    output_dir: str,
    designation_prefix: str = "openmotor_as_is",
    cd_max: float = 0.5,
    mach_max: float = 2.0,
    cd_ramp: bool = False,
    total_mass_kg: float | None = None,
    separation_delay_s: float = 0.0,
    ignition_delay_s: float = 0.0,
    target_apogee_ft: float | None = None,
    target_max_velocity_m_s: float | None = None,
) -> dict[str, object]:
    ric0 = load_ric(stage0_ric_path)
    ric1 = load_ric(stage1_ric_path)
    stage0_spec = _normalize_spec_for_motorlib(spec_from_ric(ric0))
    stage1_spec = _normalize_spec_for_motorlib(spec_from_ric(ric1))

    stage0_spec, steps0, metrics0, engine0 = _simulate_with_fallback(stage0_spec)
    stage1_spec, steps1, metrics1, engine1 = _simulate_with_fallback(stage1_spec)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    eng0 = build_eng(stage0_spec, steps0, designation=f"{designation_prefix}-S0", manufacturer="openmotor-ai")
    eng1 = build_eng(stage1_spec, steps1, designation=f"{designation_prefix}-S1", manufacturer="openmotor-ai")
    stage0_ric_out = out_dir / f"{designation_prefix}_stage0.ric"
    stage1_ric_out = out_dir / f"{designation_prefix}_stage1.ric"
    stage0_eng_out = out_dir / f"{designation_prefix}_stage0.eng"
    stage1_eng_out = out_dir / f"{designation_prefix}_stage1.eng"
    stage0_ric_out.write_text(build_ric(stage0_spec), encoding="utf-8")
    stage1_ric_out.write_text(build_ric(stage1_spec), encoding="utf-8")
    stage0_eng_out.write_text(export_eng(eng0), encoding="utf-8")
    stage1_eng_out.write_text(export_eng(eng1), encoding="utf-8")

    apogee = simulate_two_stage_apogee(
        stage0=stage0_spec,
        stage1=stage1_spec,
        rkt_path=rkt_path,
        cd_max=cd_max,
        mach_max=mach_max,
        cd_ramp=cd_ramp,
        total_mass_kg=total_mass_kg,
        separation_delay_s=separation_delay_s,
        ignition_delay_s=ignition_delay_s,
    )

    objective_reports = _objective_reports(
        apogee.apogee_m * 3.28084,
        apogee.max_velocity_m_s,
        target_apogee_ft,
        target_max_velocity_m_s,
    )

    return {
        "stage0": {
            "metrics": metrics0 | {"simulation_engine": engine0},
            "artifacts": {"ric": str(stage0_ric_out), "eng": str(stage0_eng_out)},
        },
        "stage1": {
            "metrics": metrics1 | {"simulation_engine": engine1},
            "artifacts": {"ric": str(stage1_ric_out), "eng": str(stage1_eng_out)},
        },
        "trajectory": {
            "apogee_m": apogee.apogee_m,
            "apogee_ft": apogee.apogee_m * 3.28084,
            "max_velocity_m_s": apogee.max_velocity_m_s,
            "max_accel_m_s2": apogee.max_accel_m_s2,
            "burnout_time_s": apogee.burnout_time_s,
            "cd_max": cd_max,
            "mach_max": mach_max,
            "cd_ramp": cd_ramp,
            "total_mass_kg": total_mass_kg,
            "separation_delay_s": separation_delay_s,
            "ignition_delay_s": ignition_delay_s,
        },
        "objective_reports": objective_reports,
    }


def estimate_total_impulse_ns(
    base_ric_path: str,
    stage1_ric_path: str | None,
    rkt_path: str | None,
    target_apogee_ft: float | None,
    max_velocity_m_s: float | None,
    cd_max: float,
    mach_max: float,
    cd_ramp: bool,
    total_mass_kg: float | None,
    separation_delay_s: float,
    ignition_delay_s: float,
    propellant: PropellantSpec | None = None,
) -> float:
    ric0: RicData = load_ric(base_ric_path)
    base0 = spec_from_ric(ric0)
    ric1: RicData | None = load_ric(stage1_ric_path) if stage1_ric_path else None
    base1 = spec_from_ric(ric1) if ric1 else base0
    base_prop0 = propellant or base0.propellant
    base_prop1 = propellant or base1.propellant
    base_spec0 = MotorSpec(
        config=base0.config,
        propellant=base_prop0,
        grains=base0.grains,
        nozzle=base0.nozzle,
    )
    base_spec1 = MotorSpec(
        config=base1.config,
        propellant=base_prop1,
        grains=base1.grains,
        nozzle=base1.nozzle,
    )
    base_spec0 = _normalize_spec_for_motorlib(base_spec0)
    base_spec1 = _normalize_spec_for_motorlib(base_spec1)

    try:
        base_spec0, _, metrics0, _ = _simulate_with_fallback(base_spec0)
    except Exception as exc:
        raise RuntimeError(f"Baseline stage0 simulation failed: {exc}") from exc
    try:
        base_spec1, _, metrics1, _ = _simulate_with_fallback(base_spec1)
    except Exception:
        # Fallback: use stage0 baseline when stage1 template fails
        base_spec1 = base_spec0
        metrics1 = metrics0
    base_total_impulse = metrics0["total_impulse"] + metrics1["total_impulse"]

    if not rkt_path:
        raise RuntimeError("rkt_path required for impulse estimate")
    apogee = simulate_two_stage_apogee(
        stage0=base_spec0,
        stage1=base_spec1,
        rkt_path=rkt_path,
        cd_max=cd_max,
        mach_max=mach_max,
        cd_ramp=cd_ramp,
        total_mass_kg=total_mass_kg,
        separation_delay_s=separation_delay_s,
        ignition_delay_s=ignition_delay_s,
    )
    base_apogee_ft = max(apogee.apogee_m * 3.28084, 1e-6)
    base_max_v = max(apogee.max_velocity_m_s, 1e-6)

    if target_apogee_ft is None and max_velocity_m_s is None:
        return base_total_impulse
    if target_apogee_ft is None:
        scale = max_velocity_m_s / base_max_v
    elif max_velocity_m_s is None:
        scale_apogee = max(target_apogee_ft, 1.0) / base_apogee_ft
        scale = scale_apogee**0.5
    else:
        scale_apogee = max(target_apogee_ft, 1.0) / base_apogee_ft
        scale_from_apogee = scale_apogee**0.5
        scale_from_v = max_velocity_m_s / base_max_v
        scale = 0.7 * scale_from_apogee + 0.3 * scale_from_v

    scale = max(0.4, min(scale, 3.0))
    return base_total_impulse * scale


def estimate_total_impulse_ns_single_stage(
    base_spec: MotorSpec,
    ref_diameter_m: float,
    total_mass_kg: float,
    target_apogee_ft: float | None,
    max_velocity_m_s: float | None,
    cd_max: float,
    mach_max: float,
    cd_ramp: bool,
    launch_altitude_m: float = 0.0,
    wind_speed_m_s: float = 0.0,
    temperature_k: float | None = None,
) -> float:
    base_spec = _normalize_spec_for_motorlib(base_spec)
    try:
        base_spec, _, metrics0, _ = _simulate_with_fallback(base_spec)
    except Exception as exc:
        raise RuntimeError(f"Baseline stage simulation failed: {exc}") from exc
    base_total_impulse = metrics0["total_impulse"]

    apogee = simulate_single_stage_apogee_params(
        stage=base_spec,
        ref_diameter_m=ref_diameter_m,
        total_mass_kg=total_mass_kg,
        cd_max=cd_max,
        mach_max=mach_max,
        cd_ramp=cd_ramp,
        launch_altitude_m=launch_altitude_m,
        wind_speed_m_s=wind_speed_m_s,
        temperature_k=temperature_k,
    )
    base_apogee_ft = max(apogee.apogee_m * 3.28084, 1e-6)
    base_max_v = max(apogee.max_velocity_m_s, 1e-6)

    if target_apogee_ft is None and max_velocity_m_s is None:
        return base_total_impulse
    if target_apogee_ft is None:
        scale = max_velocity_m_s / base_max_v
    elif max_velocity_m_s is None:
        scale_apogee = max(target_apogee_ft, 1.0) / base_apogee_ft
        scale = scale_apogee**0.5
    else:
        scale_apogee = max(target_apogee_ft, 1.0) / base_apogee_ft
        scale_from_apogee = scale_apogee**0.5
        scale_from_v = max_velocity_m_s / base_max_v
        scale = 0.7 * scale_from_apogee + 0.3 * scale_from_v

    scale = max(0.4, min(scale, 3.0))
    return base_total_impulse * scale


def mission_targeted_design(
    base_ric_path: str,
    stage1_ric_path: str | None,
    output_dir: str,
    rkt_path: str | None,
    total_target_impulse_ns: float | None,
    targets: TrajectoryTargets,
    constraints: TwoStageConstraints,
    search: StageSearchConfig,
    split_ratios: list[float],
    cd_max: float,
    mach_max: float,
    cd_ramp: bool,
    total_mass_kg: float | None,
    separation_delay_s: float,
    ignition_delay_s: float,
    allowed_propellant_families: list[str] | None = None,
    allowed_propellant_names: list[str] | None = None,
    preset_path: str | None = None,
    weights: ScoreWeights | None = None,
) -> dict[str, object]:
    presets = load_preset_propellants(
        preset_path
        or str(Path(__file__).resolve().parents[3] / "resources" / "propellants" / "presets.json")
    )
    selected = _filter_propellants(presets, allowed_propellant_families, allowed_propellant_names)
    if not selected:
        raise RuntimeError("No propellants matched allowed families or names.")

    ric0: RicData = load_ric(base_ric_path)
    base0 = spec_from_ric(ric0)
    ric1: RicData | None = load_ric(stage1_ric_path) if stage1_ric_path else None
    base1 = spec_from_ric(ric1) if ric1 else base0
    viable_candidates: list[Candidate] = []
    all_candidates: list[Candidate] = []
    logs: list[dict[str, object]] = []
    rejected: list[dict[str, str]] = []
    stage_cache: dict[tuple[object, ...], StageResult | None] = {}
    stage_cache: dict[tuple[object, ...], StageResult | None] = {}

    if total_target_impulse_ns is None or total_target_impulse_ns <= 0:
        baseline_prop = propellant_to_spec(selected[0])
        total_target_impulse_ns = estimate_total_impulse_ns(
            base_ric_path=base_ric_path,
            stage1_ric_path=stage1_ric_path,
            rkt_path=rkt_path,
            target_apogee_ft=targets.apogee_ft,
            max_velocity_m_s=targets.max_velocity_m_s,
            cd_max=cd_max,
            mach_max=mach_max,
            cd_ramp=cd_ramp,
            total_mass_kg=total_mass_kg,
            separation_delay_s=separation_delay_s,
            ignition_delay_s=ignition_delay_s,
            propellant=baseline_prop,
        )

    for prop in selected:
        prop_spec = propellant_to_spec(prop)
        prop_base0 = MotorSpec(
            config=base0.config,
            propellant=prop_spec,
            grains=base0.grains,
            nozzle=base0.nozzle,
        )
        prop_base1 = MotorSpec(
            config=base1.config,
            propellant=prop_spec,
            grains=base1.grains,
            nozzle=base1.nozzle,
        )
        prop_base0 = _normalize_spec_for_motorlib(prop_base0)
        prop_base1 = _normalize_spec_for_motorlib(prop_base1)
        for split in split_ratios:
            stage0_target = total_target_impulse_ns * split
            stage1_target = total_target_impulse_ns * (1.0 - split)
            try:
                stage0 = _search_stage(
                    prop_base0,
                    stage0_target,
                    search,
                    constraints,
                    reject_log=rejected,
                    reject_context={
                        "propellant": prop.name,
                        "stage": "stage0",
                        "split_ratio": f"{split:.2f}",
                    },
                )
                stage1 = _search_stage(
                    prop_base1,
                    stage1_target,
                    search,
                    constraints,
                    reject_log=rejected,
                    reject_context={
                        "propellant": prop.name,
                        "stage": "stage1",
                        "split_ratio": f"{split:.2f}",
                    },
                )
            except Exception as exc:
                rejected.append({"propellant": prop.name, "reason": str(exc)})
                continue
            if stage0 is None or stage1 is None:
                rejected.append({"propellant": prop.name, "reason": "no_feasible_stage_pair"})
                continue

            stage0_len = _stage_length_in(stage0.spec)
            stage1_len = _stage_length_in(stage1.spec)
            if stage0_len + stage1_len > constraints.max_vehicle_length_in:
                rejected.append({"propellant": prop.name, "reason": "motor stack exceeds vehicle length"})
                continue
            length_ratio = max(stage0_len, stage1_len) / max(min(stage0_len, stage1_len), 1e-6)
            if length_ratio > constraints.max_stage_length_ratio:
                rejected.append({"propellant": prop.name, "reason": "stage lengths differ too much"})
                continue
            if abs(_stage_diameter_in(stage0.spec) - _stage_diameter_in(stage1.spec)) > 1e-6:
                rejected.append({"propellant": prop.name, "reason": "stage diameters differ"})
                continue

            try:
                if not rkt_path:
                    raise RuntimeError("rkt_path required for trajectory")
                apogee = simulate_two_stage_apogee(
                    stage0=stage0.spec,
                    stage1=stage1.spec,
                    rkt_path=rkt_path,
                    cd_max=cd_max,
                    mach_max=mach_max,
                    cd_ramp=cd_ramp,
                    total_mass_kg=total_mass_kg,
                    separation_delay_s=separation_delay_s,
                    ignition_delay_s=ignition_delay_s,
                )
            except Exception as exc:
                rejected.append(
                    {"propellant": prop.name, "reason": "simulation_failed", "detail": str(exc)}
                )
                continue
            if not (apogee.apogee_m == apogee.apogee_m and apogee.max_velocity_m_s == apogee.max_velocity_m_s):
                rejected.append(
                    {
                        "propellant": prop.name,
                        "reason": "simulation_failed",
                        "detail": "NaN in trajectory output",
                    }
                )
                continue
            error = _objective_error_pct(
                apogee.apogee_m * 3.28084,
                apogee.max_velocity_m_s,
                targets.apogee_ft,
                targets.max_velocity_m_s,
            )
            if error is None:
                rejected.append({"propellant": prop.name, "reason": "no_objectives_provided"})
                continue
            within_tolerance = bool(error <= targets.tolerance_pct)
            if not within_tolerance:
                rejected.append(
                    {
                        "propellant": prop.name,
                        "reason": "objective_outside_tolerance",
                        "detail": f"error_pct={error * 100.0:.2f}",
                    }
                )

            prefix = f"mission_{_slugify_name(prop.name)}_{int(split * 100)}"
            generate_two_stage_designs(
                base_ric_path=base_ric_path,
                output_dir=output_dir,
                total_target_impulse_ns=total_target_impulse_ns,
                split_ratio=split,
                constraints=constraints,
                search=search,
                rkt_path=rkt_path,
                cd_max=cd_max,
                mach_max=mach_max,
                cd_ramp=cd_ramp,
                total_mass_kg=total_mass_kg,
                separation_delay_s=separation_delay_s,
                ignition_delay_s=ignition_delay_s,
                propellant_options=[prop_spec],
                artifact_prefix=prefix,
            )

            metrics = _combine_stage_metrics(stage0, stage1, constraints)
            metrics["max_velocity_m_s"] = apogee.max_velocity_m_s
            curve = _build_thrust_curve(stage0, stage1, separation_delay_s, ignition_delay_s)
            vehicle_len = constraints.max_vehicle_length_in
            stage_len = stage0_len + stage1_len
            stage_diameter = _stage_diameter_in(stage0.spec)
            name = f"{prop.name} split {split:.2f}"
            peak_pressure_pa = metrics.get("peak_chamber_pressure")
            peak_pressure_psi = (
                peak_pressure_pa / 6894.757 if peak_pressure_pa is not None else None
            )
            peak_kn = metrics.get("peak_kn")
            average_thrust = metrics.get("average_thrust")
            candidate = Candidate(
                name=name,
                metrics=metrics,
                thrust_curve=curve,
                apogee_ft=apogee.apogee_m * 3.28084,
                vehicle_length_in=vehicle_len,
                stage_length_in=stage_len,
                stage_diameter_in=stage_diameter,
            )
            all_candidates.append(candidate)
            if within_tolerance:
                viable_candidates.append(candidate)
            logs.append(
                {
                    "propellant": prop.name,
                    "split_ratio": split,
                    "apogee_ft": apogee.apogee_m * 3.28084,
                    "max_velocity_m_s": apogee.max_velocity_m_s,
                    "max_accel_m_s2": apogee.max_accel_m_s2,
                    "peak_pressure_psi": peak_pressure_psi,
                    "peak_kn": peak_kn,
                    "average_thrust": average_thrust,
                    "objective_reports": _objective_reports(
                        apogee.apogee_m * 3.28084,
                        apogee.max_velocity_m_s,
                        targets.apogee_ft,
                        targets.max_velocity_m_s,
                    ),
                    "objective_error_pct": float(error * 100.0),
                    "within_tolerance": within_tolerance,
                    "metrics": metrics,
                    "artifacts": {
                        "stage0_ric": str(Path(output_dir) / f"{prefix}_stage0.ric"),
                        "stage1_ric": str(Path(output_dir) / f"{prefix}_stage1.ric"),
                        "stage0_eng": str(Path(output_dir) / f"{prefix}_stage0.eng"),
                        "stage1_eng": str(Path(output_dir) / f"{prefix}_stage1.eng"),
                    },
                    "artifact_urls": {
                        "stage0_ric": f"/downloads/{(Path(output_dir) / f'{prefix}_stage0.ric').name}",
                        "stage1_ric": f"/downloads/{(Path(output_dir) / f'{prefix}_stage1.ric').name}",
                        "stage0_eng": f"/downloads/{(Path(output_dir) / f'{prefix}_stage0.eng').name}",
                        "stage1_eng": f"/downloads/{(Path(output_dir) / f'{prefix}_stage1.eng').name}",
                    },
                }
            )

    if not all_candidates:
        return _json_safe({
            "targets": {
                "apogee_ft": targets.apogee_ft,
                "max_velocity_m_s": targets.max_velocity_m_s,
                "tolerance_pct": targets.tolerance_pct,
            },
            "constraints": asdict(constraints),
            "search": asdict(search),
            "estimated_total_impulse_ns": total_target_impulse_ns,
            "summary": {
                "status": "no_viable_candidates",
                "message": "No candidates met objectives and constraints.",
            },
            "candidates": [],
            "ranked": [],
            "rejected": rejected,
        })

    ranked_pool = viable_candidates if viable_candidates else all_candidates
    scored = score_candidates(
        ranked_pool,
        p_max=constraints.max_pressure_psi * 6894.757,
        kn_max=constraints.max_kn,
        weights=weights,
    )
    ranked = [
        {
            "name": item.candidate.name,
            "total_score": item.total_score,
            "objective_scores": item.objective_scores,
            "classification": item.classification,
            "explanation": item.explanation,
            "apogee_ft": item.candidate.apogee_ft,
            "metrics": item.candidate.metrics,
            "objective_reports": _objective_reports(
                item.candidate.apogee_ft,
                item.candidate.metrics.get("max_velocity_m_s"),
                targets.apogee_ft,
                targets.max_velocity_m_s,
            ),
        }
        for item in scored
    ]

    return _json_safe({
        "targets": {
            "apogee_ft": targets.apogee_ft,
            "max_velocity_m_s": targets.max_velocity_m_s,
            "tolerance_pct": targets.tolerance_pct,
        },
        "constraints": asdict(constraints),
        "search": asdict(search),
        "estimated_total_impulse_ns": total_target_impulse_ns,
        "summary": {
            "status": "ok" if viable_candidates else "best_effort",
            "candidate_count": len(all_candidates),
            "viable_count": len(viable_candidates),
            "rejected_count": len(rejected),
        },
        "candidates": logs,
        "ranked": ranked,
        "rejected": rejected,
    })


def _default_base_spec(vehicle_params: VehicleParams, propellant: PropellantSpec) -> MotorSpec:
    diameter = max(vehicle_params.ref_diameter_m * 0.9, 0.05)
    core = diameter * 0.5
    length = max(vehicle_params.ref_diameter_m * 1.5, 0.2)
    grains = [
        BATESGrain(
            diameter_m=diameter,
            core_diameter_m=core,
            length_m=length,
            inhibited_ends="Neither",
        )
        for _ in range(3)
    ]
    throat = max(diameter * 0.25, 0.01)
    nozzle = NozzleSpec(
        throat_diameter_m=throat,
        exit_diameter_m=max(throat * 2.0, throat),
        throat_length_m=0.0,
        conv_angle_deg=35.0,
        div_angle_deg=12.0,
        efficiency=1.0,
        erosion_coeff=0.0,
        slag_coeff=0.0,
    )
    config = MotorConfig(
        amb_pressure_pa=101325.0,
        burnout_thrust_threshold_n=0.1,
        burnout_web_threshold_m=2.54e-5,
        map_dim=750,
        max_mass_flux_kg_m2_s=1400.0,
        max_pressure_pa=1.2e7,
        min_port_throat_ratio=2.0,
        timestep_s=0.03,
    )
    return MotorSpec(config=config, propellant=propellant, grains=grains, nozzle=nozzle)


def mission_targeted_design_target_only(
    *,
    output_dir: str,
    targets: TrajectoryTargets,
    constraints: TwoStageConstraints,
    search: StageSearchConfig,
    split_ratios: list[float],
    cd_max: float,
    mach_max: float,
    cd_ramp: bool,
    total_mass_kg: float | None,
    total_target_impulse_ns: float | None,
    separation_delay_s: float,
    ignition_delay_s: float,
    stage_count: int = 1,
    velocity_calibration: float = 1.0,
    fast_mode: bool = False,
    vehicle_params: VehicleParams,
    launch_altitude_m: float = 0.0,
    wind_speed_m_s: float = 0.0,
    temperature_k: float | None = None,
    allowed_propellant_families: list[str] | None = None,
    allowed_propellant_names: list[str] | None = None,
    preset_path: str | None = None,
    weights: ScoreWeights | None = None,
) -> dict[str, object]:
    if stage_count == 2 and not allowed_propellant_families and not allowed_propellant_names:
        allowed_propellant_names = list(_FAST_TARGET_ONLY_PROPELLANTS)
    presets = load_preset_propellants(
        preset_path
        or str(Path(__file__).resolve().parents[3] / "resources" / "propellants" / "presets.json")
    )
    effective_stage_ratio = (
        max(constraints.max_stage_length_ratio, 1.6) if fast_mode else constraints.max_stage_length_ratio
    )
    selected = _filter_propellants(presets, allowed_propellant_families, allowed_propellant_names)
    if not selected:
        raise RuntimeError("No propellants matched allowed families or names.")

    if total_mass_kg is None or total_mass_kg <= 0:
        raise RuntimeError("total_mass_kg is required for target-only single-stage runs.")

    seed_prop = propellant_to_spec(selected[0])
    base_spec = _default_base_spec(vehicle_params, seed_prop)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_path = out_dir / "auto_template.ric"
    base_path.write_text(build_ric(base_spec), encoding="utf-8")

    if stage_count not in (1, 2):
        raise RuntimeError("stage_count must be 1 or 2")
    if velocity_calibration <= 0:
        raise RuntimeError("velocity_calibration must be positive")

    if stage_count == 1:
        if total_target_impulse_ns is None or total_target_impulse_ns <= 0:
            total_target_impulse_ns = estimate_total_impulse_ns_single_stage(
                base_spec=base_spec,
                ref_diameter_m=vehicle_params.ref_diameter_m,
                total_mass_kg=total_mass_kg,
                target_apogee_ft=targets.apogee_ft,
                max_velocity_m_s=(
                    targets.max_velocity_m_s / velocity_calibration
                    if targets.max_velocity_m_s is not None
                    else None
                ),
                cd_max=cd_max,
                mach_max=mach_max,
                cd_ramp=cd_ramp,
                launch_altitude_m=launch_altitude_m,
                wind_speed_m_s=wind_speed_m_s,
                temperature_k=temperature_k,
            )
    else:
        if total_target_impulse_ns is None or total_target_impulse_ns <= 0:
            total_target_impulse_ns = estimate_total_impulse_ns_two_stage_params(
                base_spec0=base_spec,
                base_spec1=base_spec,
                ref_diameter_m=vehicle_params.ref_diameter_m,
                total_mass_kg=total_mass_kg,
                target_apogee_ft=targets.apogee_ft,
                max_velocity_m_s=(
                    targets.max_velocity_m_s / velocity_calibration
                    if targets.max_velocity_m_s is not None
                    else None
                ),
                cd_max=cd_max,
                mach_max=mach_max,
                cd_ramp=cd_ramp,
                separation_delay_s=separation_delay_s,
                ignition_delay_s=ignition_delay_s,
                launch_altitude_m=launch_altitude_m,
                wind_speed_m_s=wind_speed_m_s,
                temperature_k=temperature_k,
            )

    viable_candidates: list[Candidate] = []
    all_candidates: list[Candidate] = []
    logs: list[dict[str, object]] = []
    rejected: list[dict[str, str]] = []
    stage_cache: dict[tuple[object, ...], StageResult | None] = {}

    for prop in selected:
        prop_spec = propellant_to_spec(prop)
        if stage_count == 1:
            prop_base = MotorSpec(
                config=base_spec.config,
                propellant=prop_spec,
                grains=base_spec.grains,
                nozzle=base_spec.nozzle,
            )
            prop_base = _normalize_spec_for_motorlib(prop_base)
            try:
                grid = _build_stage_grid(
                    prop_base,
                    search,
                    constraints,
                    reject_log=rejected,
                    reject_context={"propellant": prop.name},
                    cache=stage_cache,
                )
            except Exception as exc:
                rejected.append({"propellant": prop.name, "reason": str(exc)})
                continue
            if not grid:
                rejected.append({"propellant": prop.name, "reason": "no_feasible_stage"})
                continue
            top_k = 3 if fast_mode else 5
            ranked = sorted(
                grid,
                key=lambda stage: abs(stage.metrics["total_impulse"] - total_target_impulse_ns),
            )[:top_k]
            best_stage = None
            best_apogee = None
            best_error = None
            for stage in ranked:
                stage_len = _stage_length_in(stage.spec)
                if stage_len > constraints.max_vehicle_length_in:
                    continue
                try:
                    apogee = simulate_single_stage_apogee_params(
                        stage=stage.spec,
                        ref_diameter_m=vehicle_params.ref_diameter_m,
                        total_mass_kg=total_mass_kg,
                        cd_max=cd_max,
                        mach_max=mach_max,
                        cd_ramp=cd_ramp,
                        launch_altitude_m=launch_altitude_m,
                        wind_speed_m_s=wind_speed_m_s,
                        temperature_k=temperature_k,
                    )
                except Exception as exc:
                    rejected.append(
                        {"propellant": prop.name, "reason": "simulation_failed", "detail": str(exc)}
                    )
                    continue
                if not (
                    apogee.apogee_m == apogee.apogee_m
                    and apogee.max_velocity_m_s == apogee.max_velocity_m_s
                ):
                    rejected.append(
                        {
                            "propellant": prop.name,
                            "reason": "simulation_failed",
                            "detail": "NaN in trajectory output",
                        }
                    )
                    continue
                calibrated_velocity = apogee.max_velocity_m_s * velocity_calibration
                error = _objective_error_pct_max(
                    apogee.apogee_m * 3.28084,
                    calibrated_velocity,
                    targets.apogee_ft,
                    targets.max_velocity_m_s,
                )
                if error is None:
                    rejected.append({"propellant": prop.name, "reason": "no_objectives_provided"})
                    continue
                if best_error is None or error < best_error:
                    best_error = error
                    best_stage = stage
                    best_apogee = apogee
            if best_stage is None or best_apogee is None or best_error is None:
                rejected.append({"propellant": prop.name, "reason": "no_viable_simulation"})
                continue

            stage_len = _stage_length_in(best_stage.spec)
            calibrated_velocity = best_apogee.max_velocity_m_s * velocity_calibration
            within_tolerance = bool(
                best_error <= targets.tolerance_pct
                and _within_max_targets(
                    best_apogee.apogee_m * 3.28084,
                    calibrated_velocity,
                    targets.apogee_ft,
                    targets.max_velocity_m_s,
                )
            )
            if not within_tolerance:
                rejected.append(
                    {
                        "propellant": prop.name,
                        "reason": "objective_outside_tolerance",
                        "detail": f"error_pct={best_error * 100.0:.2f}",
                    }
                )

            prefix = f"mission_{_slugify_name(prop.name)}"
            steps, _ = simulate_motorlib_with_result(best_stage.spec)
            eng = build_eng(best_stage.spec, steps, designation=prefix, manufacturer="openmotor-ai")
            ric_out = out_dir / f"{prefix}.ric"
            eng_out = out_dir / f"{prefix}.eng"
            ric_out.write_text(build_ric(best_stage.spec), encoding="utf-8")
            eng_out.write_text(export_eng(eng), encoding="utf-8")

            metrics = _single_stage_metrics(best_stage, constraints)
            metrics["max_velocity_m_s"] = calibrated_velocity
            curve = _build_single_stage_thrust_curve(best_stage)
            vehicle_len = vehicle_params.rocket_length_in
            stage_diameter = _stage_diameter_in(best_stage.spec)
            name = f"{prop.name} single stage"
            candidate = Candidate(
                name=name,
                metrics=metrics,
                thrust_curve=curve,
                apogee_ft=best_apogee.apogee_m * 3.28084,
                vehicle_length_in=vehicle_len,
                stage_length_in=stage_len,
                stage_diameter_in=stage_diameter,
            )
            all_candidates.append(candidate)
            if within_tolerance:
                viable_candidates.append(candidate)
            logs.append(
                {
                    "propellant": prop.name,
                    "apogee_ft": best_apogee.apogee_m * 3.28084,
                    "max_velocity_m_s": calibrated_velocity,
                    "max_velocity_m_s_raw": best_apogee.max_velocity_m_s,
                    "max_accel_m_s2": best_apogee.max_accel_m_s2,
                    "objective_reports": _objective_reports(
                        best_apogee.apogee_m * 3.28084,
                        calibrated_velocity,
                        targets.apogee_ft,
                        targets.max_velocity_m_s,
                    ),
                    "objective_error_pct": float(best_error * 100.0),
                    "within_tolerance": within_tolerance,
                    "metrics": metrics,
                    "artifacts": {
                        "ric": str(ric_out),
                        "eng": str(eng_out),
                    },
                }
            )
        else:
            prop_base0 = MotorSpec(
                config=base_spec.config,
                propellant=prop_spec,
                grains=base_spec.grains,
                nozzle=base_spec.nozzle,
            )
            prop_base1 = MotorSpec(
                config=base_spec.config,
                propellant=prop_spec,
                grains=base_spec.grains,
                nozzle=base_spec.nozzle,
            )
            prop_base0 = _normalize_spec_for_motorlib(prop_base0)
            prop_base1 = _normalize_spec_for_motorlib(prop_base1)
            best_refine: dict[str, object] | None = None
            try:
                grid0 = _build_stage_grid(
                    prop_base0,
                    search,
                    constraints,
                    reject_log=rejected,
                    reject_context={"propellant": prop.name},
                    cache=stage_cache,
                )
            except Exception as exc:
                rejected.append({"propellant": prop.name, "reason": str(exc)})
                continue
            if not grid0:
                rejected.append({"propellant": prop.name, "reason": "no_feasible_stage_pair"})
                continue
            grid_by_diameter = _group_grid_by_diameter(grid0)
            for split in split_ratios:
                stage0_target = total_target_impulse_ns * split
                stage1_target = total_target_impulse_ns * (1.0 - split)
                for diameter_key, grid_items in grid_by_diameter.items():
                    stage0 = _select_best_stage_for_target(grid_items, stage0_target)
                    stage1 = _select_best_stage_for_target(grid_items, stage1_target)
                    if stage0 is None or stage1 is None:
                        continue

                    stage0_len = _stage_length_in(stage0.spec)
                    stage1_len = _stage_length_in(stage1.spec)
                    if stage0_len + stage1_len > constraints.max_vehicle_length_in:
                        rejected.append(
                            {
                                "propellant": prop.name,
                                "split_ratio": split,
                                "reason": "motor exceeds vehicle length",
                            }
                        )
                        continue

                    length_ratio = max(stage0_len, stage1_len) / max(min(stage0_len, stage1_len), 1e-6)
                    if length_ratio > effective_stage_ratio:
                        rejected.append(
                            {
                                "propellant": prop.name,
                                "split_ratio": split,
                                "reason": "stage length ratio too large",
                            }
                        )
                        continue

                    if abs(_stage_diameter_in(stage0.spec) - _stage_diameter_in(stage1.spec)) > 1e-6:
                        rejected.append(
                            {
                                "propellant": prop.name,
                                "split_ratio": split,
                                "reason": "stage diameters must match",
                            }
                        )
                        continue

                    prop0 = stage0.metrics.get("propellant_mass", 0.0)
                    prop1 = stage1.metrics.get("propellant_mass", 0.0)
                    stage0_dry, stage1_dry = _split_stage_dry_masses(total_mass_kg, prop0, prop1)

                    try:
                        apogee = simulate_two_stage_apogee_params(
                            stage0=stage0.spec,
                            stage1=stage1.spec,
                            ref_diameter_m=vehicle_params.ref_diameter_m,
                            stage0_dry_kg=stage0_dry,
                            stage1_dry_kg=stage1_dry,
                            cd_max=cd_max,
                            mach_max=mach_max,
                            cd_ramp=cd_ramp,
                            separation_delay_s=separation_delay_s,
                            ignition_delay_s=ignition_delay_s,
                            total_mass_kg=total_mass_kg,
                            launch_altitude_m=launch_altitude_m,
                            wind_speed_m_s=wind_speed_m_s,
                            temperature_k=temperature_k,
                        )
                    except Exception as exc:
                        rejected.append(
                            {
                                "propellant": prop.name,
                                "split_ratio": split,
                                "reason": "simulation_failed",
                                "detail": str(exc),
                            }
                        )
                        continue
                    if not (
                        apogee.apogee_m == apogee.apogee_m
                        and apogee.max_velocity_m_s == apogee.max_velocity_m_s
                    ):
                        rejected.append(
                            {
                                "propellant": prop.name,
                                "split_ratio": split,
                                "reason": "simulation_failed",
                                "detail": "NaN in trajectory output",
                            }
                        )
                        continue

                    calibrated_velocity = apogee.max_velocity_m_s * velocity_calibration
                    error = _objective_error_pct_max(
                        apogee.apogee_m * 3.28084,
                        calibrated_velocity,
                        targets.apogee_ft,
                        targets.max_velocity_m_s,
                    )
                    if error is None:
                        rejected.append({"propellant": prop.name, "reason": "no_objectives_provided"})
                        continue

                    within_tolerance = bool(
                        error <= targets.tolerance_pct
                        and _within_max_targets(
                            apogee.apogee_m * 3.28084,
                            calibrated_velocity,
                            targets.apogee_ft,
                            targets.max_velocity_m_s,
                        )
                    )
                    if not within_tolerance:
                        rejected.append(
                            {
                                "propellant": prop.name,
                                "split_ratio": split,
                                "reason": "objective_outside_tolerance",
                                "detail": f"error_pct={error * 100.0:.2f}",
                            }
                        )

                    prefix = f"mission_{_slugify_name(prop.name)}_{int(split * 100)}"
                    steps0, _ = simulate_motorlib_with_result(stage0.spec)
                    steps1, _ = simulate_motorlib_with_result(stage1.spec)
                    eng0 = build_eng(
                        stage0.spec, steps0, designation=f"{prefix}-S0", manufacturer="openmotor-ai"
                    )
                    eng1 = build_eng(
                        stage1.spec, steps1, designation=f"{prefix}-S1", manufacturer="openmotor-ai"
                    )
                    stage0_ric_out = out_dir / f"{prefix}_stage0.ric"
                    stage1_ric_out = out_dir / f"{prefix}_stage1.ric"
                    stage0_eng_out = out_dir / f"{prefix}_stage0.eng"
                    stage1_eng_out = out_dir / f"{prefix}_stage1.eng"
                    stage0_ric_out.write_text(build_ric(stage0.spec), encoding="utf-8")
                    stage1_ric_out.write_text(build_ric(stage1.spec), encoding="utf-8")
                    stage0_eng_out.write_text(export_eng(eng0), encoding="utf-8")
                    stage1_eng_out.write_text(export_eng(eng1), encoding="utf-8")

                    metrics = _combine_stage_metrics(stage0, stage1, constraints)
                    metrics["max_velocity_m_s"] = calibrated_velocity
                    curve = _build_thrust_curve(stage0, stage1, separation_delay_s, ignition_delay_s)
                    vehicle_len = vehicle_params.rocket_length_in
                    stage_diameter = _stage_diameter_in(stage0.spec)
                    name = f"{prop.name} two stage"
                    candidate = Candidate(
                        name=name,
                        metrics=metrics,
                        thrust_curve=curve,
                        apogee_ft=apogee.apogee_m * 3.28084,
                        vehicle_length_in=vehicle_len,
                        stage_length_in=stage0_len + stage1_len,
                        stage_diameter_in=stage_diameter,
                    )
                    all_candidates.append(candidate)
                    if within_tolerance:
                        viable_candidates.append(candidate)
                    if best_refine is None or error < best_refine["error_pct"]:
                        best_refine = {
                            "propellant": prop,
                            "split_ratio": split,
                            "diameter_scale": diameter_key,
                            "stage0": stage0,
                            "stage1": stage1,
                            "error_pct": error,
                        }
                    logs.append(
                        {
                            "propellant": prop.name,
                            "split_ratio": split,
                            "apogee_ft": apogee.apogee_m * 3.28084,
                            "max_velocity_m_s": calibrated_velocity,
                            "max_velocity_m_s_raw": apogee.max_velocity_m_s,
                            "max_accel_m_s2": apogee.max_accel_m_s2,
                            "objective_reports": _objective_reports(
                                apogee.apogee_m * 3.28084,
                                calibrated_velocity,
                                targets.apogee_ft,
                                targets.max_velocity_m_s,
                            ),
                            "objective_error_pct": float(error * 100.0),
                            "within_tolerance": within_tolerance,
                            "metrics": metrics,
                            "artifacts": {
                                "stage0_ric": str(stage0_ric_out),
                                "stage1_ric": str(stage1_ric_out),
                                "stage0_eng": str(stage0_eng_out),
                                "stage1_eng": str(stage1_eng_out),
                            },
                        }
                    )
            if best_refine and best_refine["stage0"].scales and best_refine["stage1"].scales:
                refined_splits = _refine_split_ratios(float(best_refine["split_ratio"]))
                refined_search0 = _refine_search_config(
                    search,
                    best_refine["stage0"].scales,
                    fixed_diameter=float(best_refine["diameter_scale"]),
                    spread=0.05 if fast_mode else 0.04,
                )
                refined_search1 = _refine_search_config(
                    search,
                    best_refine["stage1"].scales,
                    fixed_diameter=float(best_refine["diameter_scale"]),
                    spread=0.05 if fast_mode else 0.04,
                )
                grid0_refined = _build_stage_grid(
                    prop_base0,
                    refined_search0,
                    constraints,
                    reject_log=rejected,
                    reject_context={"propellant": prop.name, "refined": "stage0"},
                    cache=stage_cache,
                )
                grid1_refined = _build_stage_grid(
                    prop_base1,
                    refined_search1,
                    constraints,
                    reject_log=rejected,
                    reject_context={"propellant": prop.name, "refined": "stage1"},
                    cache=stage_cache,
                )
                if grid0_refined and grid1_refined:
                    for split in refined_splits:
                        stage0_target = total_target_impulse_ns * split
                        stage1_target = total_target_impulse_ns * (1.0 - split)
                        stage0 = _select_best_stage_for_target(grid0_refined, stage0_target)
                        stage1 = _select_best_stage_for_target(grid1_refined, stage1_target)
                        if stage0 is None or stage1 is None:
                            continue
                        stage0_len = _stage_length_in(stage0.spec)
                        stage1_len = _stage_length_in(stage1.spec)
                        if stage0_len + stage1_len > constraints.max_vehicle_length_in:
                            continue
                        length_ratio = max(stage0_len, stage1_len) / max(
                            min(stage0_len, stage1_len), 1e-6
                        )
                        if length_ratio > effective_stage_ratio:
                            continue
                        if abs(_stage_diameter_in(stage0.spec) - _stage_diameter_in(stage1.spec)) > 1e-6:
                            continue
                        prop0 = stage0.metrics.get("propellant_mass", 0.0)
                        prop1 = stage1.metrics.get("propellant_mass", 0.0)
                        stage0_dry, stage1_dry = _split_stage_dry_masses(total_mass_kg, prop0, prop1)
                        try:
                            apogee = simulate_two_stage_apogee_params(
                                stage0=stage0.spec,
                                stage1=stage1.spec,
                                ref_diameter_m=vehicle_params.ref_diameter_m,
                                stage0_dry_kg=stage0_dry,
                                stage1_dry_kg=stage1_dry,
                                cd_max=cd_max,
                                mach_max=mach_max,
                                cd_ramp=cd_ramp,
                                separation_delay_s=separation_delay_s,
                                ignition_delay_s=ignition_delay_s,
                                total_mass_kg=total_mass_kg,
                                launch_altitude_m=launch_altitude_m,
                                wind_speed_m_s=wind_speed_m_s,
                                temperature_k=temperature_k,
                            )
                        except Exception:
                            continue
                        if not (
                            apogee.apogee_m == apogee.apogee_m
                            and apogee.max_velocity_m_s == apogee.max_velocity_m_s
                        ):
                            continue
                        calibrated_velocity = apogee.max_velocity_m_s * velocity_calibration
                        error = _objective_error_pct_max(
                            apogee.apogee_m * 3.28084,
                            calibrated_velocity,
                            targets.apogee_ft,
                            targets.max_velocity_m_s,
                        )
                        if error is None:
                            continue
                        within_tolerance = bool(
                            error <= targets.tolerance_pct
                            and _within_max_targets(
                                apogee.apogee_m * 3.28084,
                                calibrated_velocity,
                                targets.apogee_ft,
                                targets.max_velocity_m_s,
                            )
                        )
                        prefix = f"mission_{_slugify_name(prop.name)}_{int(split * 100)}"
                        steps0, _ = simulate_motorlib_with_result(stage0.spec)
                        steps1, _ = simulate_motorlib_with_result(stage1.spec)
                        eng0 = build_eng(
                            stage0.spec, steps0, designation=f"{prefix}-S0", manufacturer="openmotor-ai"
                        )
                        eng1 = build_eng(
                            stage1.spec, steps1, designation=f"{prefix}-S1", manufacturer="openmotor-ai"
                        )
                        stage0_ric_out = out_dir / f"{prefix}_stage0.ric"
                        stage1_ric_out = out_dir / f"{prefix}_stage1.ric"
                        stage0_eng_out = out_dir / f"{prefix}_stage0.eng"
                        stage1_eng_out = out_dir / f"{prefix}_stage1.eng"
                        stage0_ric_out.write_text(build_ric(stage0.spec), encoding="utf-8")
                        stage1_ric_out.write_text(build_ric(stage1.spec), encoding="utf-8")
                        stage0_eng_out.write_text(export_eng(eng0), encoding="utf-8")
                        stage1_eng_out.write_text(export_eng(eng1), encoding="utf-8")
                        metrics = _combine_stage_metrics(stage0, stage1, constraints)
                        metrics["max_velocity_m_s"] = calibrated_velocity
                        curve = _build_thrust_curve(stage0, stage1, separation_delay_s, ignition_delay_s)
                        vehicle_len = vehicle_params.rocket_length_in
                        stage_diameter = _stage_diameter_in(stage0.spec)
                        name = f"{prop.name} two stage"
                        candidate = Candidate(
                            name=name,
                            metrics=metrics,
                            thrust_curve=curve,
                            apogee_ft=apogee.apogee_m * 3.28084,
                            vehicle_length_in=vehicle_len,
                            stage_length_in=stage0_len + stage1_len,
                            stage_diameter_in=stage_diameter,
                        )
                        all_candidates.append(candidate)
                        if within_tolerance:
                            viable_candidates.append(candidate)
                        logs.append(
                            {
                                "propellant": prop.name,
                                "split_ratio": split,
                                "apogee_ft": apogee.apogee_m * 3.28084,
                                "max_velocity_m_s": calibrated_velocity,
                                "max_velocity_m_s_raw": apogee.max_velocity_m_s,
                                "max_accel_m_s2": apogee.max_accel_m_s2,
                                "objective_reports": _objective_reports(
                                    apogee.apogee_m * 3.28084,
                                    calibrated_velocity,
                                    targets.apogee_ft,
                                    targets.max_velocity_m_s,
                                ),
                                "objective_error_pct": float(error * 100.0),
                                "within_tolerance": within_tolerance,
                                "metrics": metrics,
                                "artifacts": {
                                    "stage0_ric": str(stage0_ric_out),
                                    "stage1_ric": str(stage1_ric_out),
                                    "stage0_eng": str(stage0_eng_out),
                                    "stage1_eng": str(stage1_eng_out),
                                },
                            }
                        )

    if not all_candidates:
        return _json_safe({
            "targets": {
                "apogee_ft": targets.apogee_ft,
                "max_velocity_m_s": targets.max_velocity_m_s,
                "tolerance_pct": targets.tolerance_pct,
            },
            "constraints": asdict(constraints),
            "search": asdict(search),
            "estimated_total_impulse_ns": total_target_impulse_ns,
            "summary": {
                "status": "no_viable_candidates",
                "message": "No candidates met objectives and constraints.",
            },
            "candidates": [],
            "ranked": [],
            "rejected": rejected,
        })

    ranked_pool = viable_candidates if viable_candidates else all_candidates
    ranked = []
    for item in sorted(
        ranked_pool,
        key=lambda cand: _objective_error_pct_max(
            cand.apogee_ft,
            cand.metrics.get("max_velocity_m_s"),
            targets.apogee_ft,
            targets.max_velocity_m_s,
        )
        or 1e9,
    ):
        ranked.append(
            {
                "name": item.name,
                "apogee_ft": item.apogee_ft,
                "metrics": item.metrics,
                "objective_reports": _objective_reports(
                    item.apogee_ft,
                    item.metrics.get("max_velocity_m_s"),
                    targets.apogee_ft,
                    targets.max_velocity_m_s,
                ),
            }
        )

    return _json_safe({
        "targets": {
            "apogee_ft": targets.apogee_ft,
            "max_velocity_m_s": targets.max_velocity_m_s,
            "tolerance_pct": targets.tolerance_pct,
        },
        "constraints": asdict(constraints),
        "search": asdict(search),
        "estimated_total_impulse_ns": total_target_impulse_ns,
        "summary": {
            "status": "ok" if viable_candidates else "best_effort",
            "candidate_count": len(all_candidates),
            "viable_count": len(viable_candidates),
            "rejected_count": len(rejected),
        },
        "candidates": logs,
        "ranked": ranked,
        "rejected": rejected,
    })


def optimize_two_stage_for_targets(
    base_ric_path: str,
    output_dir: str,
    targets: TrajectoryTargets,
    total_target_impulse_ns: float,
    constraints: TwoStageConstraints,
    search: StageSearchConfig,
    split_ratios: list[float],
    cd_max: float,
    mach_max: float,
    cd_ramp: bool,
    total_mass_kg: float | None,
    rkt_path: str,
    separation_delay_s: float = 0.0,
    ignition_delay_s: float = 0.0,
) -> dict[str, dict[str, float]]:
    best_log = None
    best_error = None
    for split in split_ratios:
        log = generate_two_stage_designs(
            base_ric_path=base_ric_path,
            output_dir=output_dir,
            total_target_impulse_ns=total_target_impulse_ns,
            split_ratio=split,
            constraints=constraints,
            search=search,
            rkt_path=rkt_path,
            cd_max=cd_max,
            mach_max=mach_max,
            cd_ramp=cd_ramp,
            total_mass_kg=total_mass_kg,
            separation_delay_s=separation_delay_s,
            ignition_delay_s=ignition_delay_s,
        )
        if "apogee" not in log:
            continue
        apogee_ft = log["apogee"]["apogee_ft"]
        error = abs(apogee_ft - targets.apogee_ft) / max(targets.apogee_ft, 1e-6)
        if targets.max_velocity_m_s is not None:
            v_err = abs(log["apogee"]["max_velocity_m_s"] - targets.max_velocity_m_s) / max(
                targets.max_velocity_m_s, 1e-6
            )
            error = 0.7 * error + 0.3 * v_err
        if best_error is None or error < best_error:
            best_error = error
            best_log = log

    if best_log is None:
        raise RuntimeError("No feasible design found for trajectory targets.")

    best_log["targets"] = best_log["targets"] | {
        "target_apogee_ft": targets.apogee_ft,
        "target_max_velocity_m_s": targets.max_velocity_m_s,
        "tolerance_pct": targets.tolerance_pct,
        "cd_max": cd_max,
        "mach_max": mach_max,
        "cd_ramp": cd_ramp,
        "total_mass_kg": total_mass_kg,
        "separation_delay_s": separation_delay_s,
        "ignition_delay_s": ignition_delay_s,
    }
    best_log["fit"] = {
        "error_pct": best_error * 100.0,
        "meets_tolerance": best_error <= targets.tolerance_pct,
    }
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    (Path(output_dir) / "openmotor_ai_fit_metrics.json").write_text(
        __import__("json").dumps(best_log, indent=2),
        encoding="utf-8",
    )
    return best_log
