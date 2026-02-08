from __future__ import annotations

from dataclasses import dataclass, asdict
import re
from pathlib import Path
from typing import Callable, Iterable

from app.engine.openmotor_ai.eng_builder import build_eng
from app.engine.openmotor_ai.eng_export import export_eng
from app.engine.openmotor_ai.motorlib_adapter import (
    metrics_from_simresult,
    simulate_motorlib_with_result,
)
from app.engine.openmotor_ai.propellant_library import load_openmotor_propellants, load_preset_propellants
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
from app.engine.openmotor_ai.smart_nozzle_architect import SmartNozzleArchitect
from app.engine.openmotor_ai.trajectory import (
    simulate_single_stage_apogee_params,
    simulate_two_stage_apogee,
    simulate_two_stage_apogee_params,
)
from app.services.motor_classifier import ClassificationRequest, calculate_motor_requirements


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

_VEHICLE_DIM_TOLERANCE_PCT = 0.06
_RELAXED_STAGE_LENGTH_RATIO = 2.5
_PREFERRED_PROPELLANT_ORDER = [
    "RCS - Blue Thunder",
    "White Lightning",
    "Black Jack",
    "Green Gorilla",
    "RCS - Warp 9",
    "MIT - Cherry Limeade",
    "MIT - Ocean Water",
    "Skidmark",
    "Redline",
    "AP/Al/HTPB",
    "AP/HTPB",
    "ANCP",
    "APCP",
    "HTPB (hybrid fuel grain)",
    "Composite Propellant",
    "Sugar Propellant",
    "Nakka - KNSB",
    "KNSU",
    "KNDX",
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
    grains = list(base.grains)
    if grain_count:
        if len(grains) < grain_count and grains:
            # Expand grain stack to requested count by repeating last grain geometry.
            grains.extend([grains[-1]] * (grain_count - len(grains)))
        grains = grains[:grain_count]
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
    max_pressure = constraints.max_pressure_psi * 1.01
    return peak_pressure_psi <= max_pressure and metrics["peak_kn"] <= constraints.max_kn


def _search_stage(
    base: MotorSpec,
    target_impulse_ns: float,
    search: StageSearchConfig,
    constraints: TwoStageConstraints,
    fixed_diameter_scale: float | None = None,
    exclude_scales: StageScales | None = None,
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
                        candidate_scales = StageScales(
                            diameter_scale=diameter_scale,
                            length_scale=length_scale,
                            core_scale=core_scale,
                            throat_scale=throat_scale,
                            exit_scale=exit_scale,
                        )
                        if exclude_scales is not None and candidate_scales == exclude_scales:
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
                                scales=candidate_scales,
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


def _same_stage_scales(stage_a: StageResult, stage_b: StageResult) -> bool:
    if not stage_a.scales or not stage_b.scales:
        return False
    return stage_a.scales == stage_b.scales


def _float_close(a: float | None, b: float | None, tol: float = 1e-6) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def _resolve_output_dir(output_dir: str) -> Path:
    path = Path(output_dir)
    if path.is_absolute():
        return path
    normalized = path.as_posix()
    backend_root = Path(__file__).resolve().parents[3]
    if normalized.startswith("backend/"):
        normalized = normalized[len("backend/") :]
    return backend_root / normalized


def _downloads_root() -> Path:
    return Path(__file__).resolve().parents[3] / "tests"


def _download_url(output_root: Path, filename: str) -> str:
    try:
        relative = output_root.resolve().relative_to(_downloads_root().resolve())
        prefix = f"{relative.as_posix()}/" if relative.parts else ""
    except ValueError:
        prefix = ""
    return f"/downloads/{prefix}{filename}"


def _relative_delta(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    denom = max(abs(a), abs(b), 1e-9)
    return abs(a - b) / denom


def _pressure_bounds_psi(constraints: TwoStageConstraints, tolerance_pct: float = 0.01) -> tuple[float, float]:
    max_pressure = constraints.max_pressure_psi
    tol = abs(tolerance_pct)
    return max_pressure * (1.0 - tol), max_pressure * (1.0 + tol)


def _pressure_within_tolerance(
    metrics: dict[str, float],
    constraints: TwoStageConstraints,
    tolerance_pct: float = 0.01,
) -> bool:
    peak_pa = metrics.get("peak_chamber_pressure")
    if peak_pa is None:
        return False
    peak_psi = peak_pa / 6894.757
    low, high = _pressure_bounds_psi(constraints, tolerance_pct)
    return low <= peak_psi <= high


def _total_mass_from_dry(dry_mass_kg: float, *metric_dicts: dict[str, float]) -> float:
    prop_total = 0.0
    for metrics in metric_dicts:
        prop_total += float(metrics.get("propellant_mass", 0.0) or 0.0)
    return max(dry_mass_kg + prop_total, 1e-6)


def _estimate_impulse_motor_solver(
    target_apogee_ft: float | None,
    dry_mass_kg: float,
    ref_diameter_m: float,
    cd_max: float,
    isp: float = 200.0,
) -> tuple[float | None, dict[str, float | str] | None]:
    if not target_apogee_ft or target_apogee_ft <= 0:
        return None, None
    from app.engine.openmotor_ai.motor_solver import MotorSolver

    solver = MotorSolver()
    result = solver.solve(
        target_altitude_m=float(target_apogee_ft) * 0.3048,
        dry_mass_kg=float(dry_mass_kg),
        diameter_m=float(ref_diameter_m),
        cd=float(cd_max),
        isp=float(isp),
    )
    return float(result["impulse_required"]), result


def _expand_search_for_pressure(search: StageSearchConfig, factor: float = 1.25) -> StageSearchConfig:
    def _expand(values: list[float], multipliers: list[float]) -> list[float]:
        if not values:
            return values
        base_max = max(values)
        expanded = set(values)
        for mult in multipliers:
            expanded.add(base_max * mult)
        return sorted(expanded)

    multipliers = [factor, factor * factor, factor * factor * factor]
    return search.__class__(
        diameter_scales=_expand(search.diameter_scales, [1.1, 1.2]),
        length_scales=_expand(search.length_scales, [1.15, 1.3]),
        core_scales=_expand(search.core_scales, multipliers),
        throat_scales=_expand(search.throat_scales, multipliers),
        exit_scales=_expand(search.exit_scales, [1.1, 1.25]),
        grain_count=search.grain_count,
    )


def _stages_too_similar(
    stage_a: StageResult,
    stage_b: StageResult,
    min_rel_delta: float = 0.03,
) -> bool:
    keys = (
        "total_impulse",
        "propellant_mass_lb",
        "propellant_length_in",
        "average_thrust",
        "peak_kn",
    )
    deltas: list[float] = []
    for key in keys:
        delta = _relative_delta(stage_a.metrics.get(key), stage_b.metrics.get(key))
        if delta is not None:
            deltas.append(delta)
    if not deltas:
        return False
    return all(delta < min_rel_delta for delta in deltas)


def _candidate_key(name: str, metrics: dict[str, float], apogee_ft: float | None) -> str:
    def _round(value: float | None) -> float | None:
        if value is None:
            return None
        return round(float(value), 6)

    return "|".join(
        [
            name,
            str(_round(apogee_ft)),
            str(_round(metrics.get("total_impulse"))),
            str(_round(metrics.get("propellant_mass_lb"))),
            str(_round(metrics.get("propellant_length_in"))),
            str(_round(metrics.get("max_velocity_m_s"))),
        ]
    )


def _find_log_for_candidate(
    logs: list[dict[str, object]], name: str, metrics: dict[str, float], apogee_ft: float | None
) -> dict[str, object] | None:
    candidate_key = _candidate_key(name, metrics, apogee_ft)
    for log in logs:
        if log.get("candidate_key") == candidate_key:
            return log
    target_total = metrics.get("total_impulse")
    target_mass = metrics.get("propellant_mass_lb")
    target_length = metrics.get("propellant_length_in")
    for log in logs:
        if log.get("name") != name:
            continue
        log_metrics = log.get("metrics") or {}
        if not isinstance(log_metrics, dict):
            continue
        if (
            _float_close(log_metrics.get("total_impulse"), target_total)
            and _float_close(log_metrics.get("propellant_mass_lb"), target_mass)
            and _float_close(log_metrics.get("propellant_length_in"), target_length)
        ):
            return log
    return None


def _find_log_by_name_closest(
    logs: list[dict[str, object]], name: str, metrics: dict[str, float]
) -> dict[str, object] | None:
    target_total = metrics.get("total_impulse")
    best_log = None
    best_delta = None
    for log in logs:
        if log.get("name") != name:
            continue
        log_metrics = log.get("metrics") or {}
        if not isinstance(log_metrics, dict):
            continue
        log_total = log_metrics.get("total_impulse")
        if target_total is None or log_total is None:
            continue
        delta = abs(log_total - target_total)
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_log = log
    return best_log


def _select_best_stage_for_target(
    grid: list[StageResult],
    target_impulse_ns: float,
    exclude: StageResult | None = None,
) -> StageResult | None:
    if not grid:
        return None
    best = None
    best_score = None
    for stage in grid:
        if exclude is not None and (
            stage is exclude
            or _same_stage_scales(stage, exclude)
            or _stages_too_similar(stage, exclude)
        ):
            continue
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
    if stage0_len + stage1_len > constraints.max_vehicle_length_in * (1.0 + _VEHICLE_DIM_TOLERANCE_PCT):
        raise RuntimeError("Motor stack exceeds vehicle length constraint.")
    length_ratio = max(stage0_len, stage1_len) / max(min(stage0_len, stage1_len), 1e-6)
    if length_ratio > max(constraints.max_stage_length_ratio, _RELAXED_STAGE_LENGTH_RATIO):
        raise RuntimeError("Stage lengths differ too much for two-stage packaging.")

    out_dir = _resolve_output_dir(output_dir)
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

    stage0_ric_path = out_dir / f"{artifact_prefix}_stage0.ric"
    stage1_ric_path = out_dir / f"{artifact_prefix}_stage1.ric"
    stage0_metrics = _stage_metrics_from_ric_or_spec(stage0, stage0_ric_path)
    stage1_metrics = _stage_metrics_from_ric_or_spec(stage1, stage1_ric_path)

    apogee = None
    total_mass_for_sim = (
        _total_mass_from_dry(total_mass_kg, stage0_metrics, stage1_metrics)
        if total_mass_kg is not None
        else None
    )
    if rkt_path:
        apogee = simulate_two_stage_apogee(
            stage0=stage0.spec,
            stage1=stage1.spec,
            rkt_path=rkt_path,
            cd_max=cd_max,
            mach_max=mach_max,
            cd_ramp=cd_ramp,
            total_mass_kg=total_mass_for_sim,
            separation_delay_s=separation_delay_s,
            ignition_delay_s=ignition_delay_s,
        )

    log = {
        "stage0": _metrics_with_units(stage0_metrics)
        | {"stage_length_in": stage0_len, "stage_diameter_in": _stage_diameter_in(stage0.spec)},
        "stage1": _metrics_with_units(stage1_metrics)
        | {"stage_length_in": stage1_len, "stage_diameter_in": _stage_diameter_in(stage1.spec)},
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
            "total_mass_kg": total_mass_for_sim,
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
    if stage_len > constraints.max_vehicle_length_in * (1.0 + _VEHICLE_DIM_TOLERANCE_PCT):
        raise RuntimeError("Motor length exceeds vehicle length constraint.")

    out_dir = _resolve_output_dir(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    steps, _ = simulate_motorlib_with_result(best.spec)
    eng = build_eng(best.spec, steps, designation=artifact_prefix, manufacturer="openmotor-ai")
    ric_out = out_dir / f"{artifact_prefix}.ric"
    eng_out = out_dir / f"{artifact_prefix}.eng"
    ric_out.write_text(build_ric(best.spec), encoding="utf-8")
    eng_out.write_text(export_eng(eng), encoding="utf-8")

    stage_metrics = _stage_metrics_from_ric_or_spec(best, ric_out)

    apogee = None
    total_mass_for_sim = (
        _total_mass_from_dry(total_mass_kg, best.metrics) if total_mass_kg is not None else None
    )
    if ref_diameter_m is not None and total_mass_for_sim is not None:
        apogee = simulate_single_stage_apogee_params(
            stage=best.spec,
            ref_diameter_m=ref_diameter_m,
            total_mass_kg=total_mass_for_sim,
            cd_max=cd_max,
            mach_max=mach_max,
            cd_ramp=cd_ramp,
            launch_altitude_m=launch_altitude_m,
            wind_speed_m_s=wind_speed_m_s,
            temperature_k=temperature_k,
            rod_length_m=rod_length_m,
            launch_angle_deg=launch_angle_deg,
        )

    log = {
        "stage": _metrics_with_units(stage_metrics)
        | {"stage_length_in": stage_len, "stage_diameter_in": _stage_diameter_in(best.spec)},
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
            "total_mass_kg": total_mass_for_sim,
        }
    (out_dir / f"{artifact_prefix}_metrics.json").write_text(
        __import__("json").dumps(log, indent=2),
        encoding="utf-8",
    )
    return log


def _combine_metric_dicts(
    metrics0: dict[str, float],
    metrics1: dict[str, float],
    constraints: TwoStageConstraints,
) -> dict[str, float]:
    m0 = metrics0
    m1 = metrics1
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


def _combine_stage_metrics(
    stage0: StageResult,
    stage1: StageResult,
    constraints: TwoStageConstraints,
) -> dict[str, float]:
    return _combine_metric_dicts(stage0.metrics, stage1.metrics, constraints)


def _metrics_from_ric_path(ric_path: Path) -> dict[str, float] | None:
    from app.engine.openmotor_ai.motorlib_adapter import (
        metrics_from_simresult,
        simulate_motorlib_with_result_from_ric,
    )

    try:
        _, sim = simulate_motorlib_with_result_from_ric(str(ric_path))
    except Exception:
        return None
    metrics = metrics_from_simresult(sim)
    metrics["simulation_engine"] = "openmotor_ric"
    return metrics


def _stage_metrics_from_ric_or_spec(stage: StageResult, ric_path: Path | None) -> dict[str, float]:
    if ric_path is None:
        return stage.metrics
    metrics = _metrics_from_ric_path(ric_path)
    return metrics or stage.metrics


def _build_thrust_curve_from_ric_paths(
    stage0_ric: Path | None,
    stage1_ric: Path | None,
    separation_delay_s: float,
    ignition_delay_s: float,
) -> list[tuple[float, float]]:
    if stage0_ric is None or stage1_ric is None:
        return []
    from app.engine.openmotor_ai.motorlib_adapter import simulate_motorlib_with_result_from_ric

    try:
        steps0, _ = simulate_motorlib_with_result_from_ric(str(stage0_ric))
        steps1, _ = simulate_motorlib_with_result_from_ric(str(stage1_ric))
    except Exception:
        return []
    curve: list[tuple[float, float]] = []
    for step in steps0:
        curve.append((step.time_s, step.thrust_n))
    offset = (steps0[-1].time_s if steps0 else 0.0) + separation_delay_s + ignition_delay_s
    if separation_delay_s + ignition_delay_s > 0.0:
        curve.append((offset, 0.0))
    for step in steps1:
        curve.append((step.time_s + offset, step.thrust_n))
    return curve


def _build_single_stage_thrust_curve_from_ric(ric_path: Path | None) -> list[tuple[float, float]]:
    if ric_path is None:
        return []
    from app.engine.openmotor_ai.motorlib_adapter import simulate_motorlib_with_result_from_ric

    try:
        steps, _ = simulate_motorlib_with_result_from_ric(str(ric_path))
    except Exception:
        return []
    return [(step.time_s, step.thrust_n) for step in steps]


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
    return _single_stage_metric_dict(stage.metrics, constraints)


def _single_stage_metric_dict(metrics: dict[str, float], constraints: TwoStageConstraints) -> dict[str, float]:
    out = dict(metrics)
    out["max_pressure"] = constraints.max_pressure_psi * 6894.757
    out["max_kn"] = constraints.max_kn
    return out


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


def _propellant_spec_key(spec: PropellantSpec) -> tuple[object, ...]:
    tab_key = tuple(
        (
            round(tab.a, 12),
            round(tab.n, 6),
            round(tab.k, 6),
            round(tab.m, 6),
            round(tab.t, 3),
            round(tab.min_pressure_pa, 2),
            round(tab.max_pressure_pa, 2),
        )
        for tab in spec.tabs
    )
    return (spec.name, round(spec.density_kg_m3, 6), tab_key)


def _dedupe_propellant_specs(specs: list[PropellantSpec]) -> list[PropellantSpec]:
    seen: set[tuple[object, ...]] = set()
    unique: list[PropellantSpec] = []
    for spec in specs:
        key = _propellant_spec_key(spec)
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
    return unique


def _load_propellant_specs(
    *,
    preset_path: str | None,
    allowed_propellant_families: list[str] | None,
    allowed_propellant_names: list[str] | None,
) -> list[PropellantSpec]:
    default_path = str(Path(__file__).resolve().parents[3] / "resources" / "propellants" / "presets.json")
    presets = load_preset_propellants(default_path)
    if preset_path:
        presets += load_preset_propellants(preset_path)
    if allowed_propellant_families or allowed_propellant_names:
        selected = _filter_propellants(presets, allowed_propellant_families, allowed_propellant_names)
    else:
        selected = presets
    if not selected:
        raise RuntimeError("No propellants matched allowed families or names.")
    specs = [propellant_to_spec(prop) for prop in selected]

    try:
        openmotor_root = Path(__file__).resolve().parents[3] / "third_party" / "openmotor_src"
        for entry in load_openmotor_propellants(str(openmotor_root)):
            if allowed_propellant_names and entry.name not in allowed_propellant_names:
                continue
            specs.append(
                PropellantSpec(
                    name=entry.name,
                    density_kg_m3=entry.density_kg_m3,
                    tabs=entry.tabs,
                )
            )
    except Exception:
        pass
    deduped = _dedupe_propellant_specs(specs)
    if allowed_propellant_names:
        order = {name: idx for idx, name in enumerate(allowed_propellant_names)}
        deduped.sort(key=lambda spec: order.get(spec.name, len(order)))
        deduped = [spec for spec in deduped if spec.name in order]
    return deduped


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
    rod_length_m: float = 0.0,
    launch_angle_deg: float = 0.0,
) -> float:
    impulse_estimate, _ = _estimate_impulse_motor_solver(
        target_apogee_ft=target_apogee_ft,
        dry_mass_kg=total_mass_kg,
        ref_diameter_m=ref_diameter_m,
        cd_max=cd_max,
    )
    if impulse_estimate is not None:
        return impulse_estimate
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
    total_mass_kg = _total_mass_from_dry(total_mass_kg, metrics0, metrics1)
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
        rod_length_m=rod_length_m,
        launch_angle_deg=launch_angle_deg,
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

    out_dir = _resolve_output_dir(output_dir)
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

    total_mass_for_sim = (
        _total_mass_from_dry(total_mass_kg, metrics0, metrics1)
        if total_mass_kg is not None
        else None
    )
    apogee = simulate_two_stage_apogee(
        stage0=stage0_spec,
        stage1=stage1_spec,
        rkt_path=rkt_path,
        cd_max=cd_max,
        mach_max=mach_max,
        cd_ramp=cd_ramp,
        total_mass_kg=total_mass_for_sim,
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
            "total_mass_kg": total_mass_for_sim,
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
    total_mass_kg = (
        _total_mass_from_dry(total_mass_kg, metrics0, metrics1)
        if total_mass_kg is not None
        else None
    )
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
    rod_length_m: float = 0.0,
    launch_angle_deg: float = 0.0,
) -> float:
    impulse_estimate, _ = _estimate_impulse_motor_solver(
        target_apogee_ft=target_apogee_ft,
        dry_mass_kg=total_mass_kg,
        ref_diameter_m=ref_diameter_m,
        cd_max=cd_max,
    )
    if impulse_estimate is not None:
        return impulse_estimate
    base_spec = _normalize_spec_for_motorlib(base_spec)
    try:
        base_spec, _, metrics0, _ = _simulate_with_fallback(base_spec)
    except Exception as exc:
        raise RuntimeError(f"Baseline stage simulation failed: {exc}") from exc
    base_total_impulse = metrics0["total_impulse"]

    total_mass_kg = _total_mass_from_dry(total_mass_kg, metrics0)
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
        rod_length_m=rod_length_m,
        launch_angle_deg=launch_angle_deg,
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
    output_root = _resolve_output_dir(output_dir)
    propellant_specs = _load_propellant_specs(
        preset_path=preset_path,
        allowed_propellant_families=allowed_propellant_families,
        allowed_propellant_names=(
            allowed_propellant_names or _PREFERRED_PROPELLANT_ORDER
        ),
    )

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
    same_base_template = stage1_ric_path is None

    if total_target_impulse_ns is None or total_target_impulse_ns <= 0:
        baseline_prop = propellant_specs[0]
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

    for prop_spec in propellant_specs:
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
                        "propellant": prop_spec.name,
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
                        "propellant": prop_spec.name,
                        "stage": "stage1",
                        "split_ratio": f"{split:.2f}",
                    },
                )
                if stage0 is not None and stage1 is not None:
                    needs_alternate = same_base_template and (
                        _same_stage_scales(stage0, stage1) or _stages_too_similar(stage0, stage1)
                    )
                    if needs_alternate:
                        stage1 = _search_stage(
                            prop_base1,
                            stage1_target,
                            search,
                            constraints,
                            exclude_scales=stage0.scales,
                            reject_log=rejected,
                            reject_context={
                                "propellant": prop_spec.name,
                                "stage": "stage1",
                                "split_ratio": f"{split:.2f}",
                                "reason": "stage_specs_too_similar",
                            },
                        )
            except Exception as exc:
                rejected.append({"propellant": prop_spec.name, "reason": str(exc)})
                continue
            if stage0 is None or stage1 is None:
                rejected.append({"propellant": prop_spec.name, "reason": "no_feasible_stage_pair"})
                continue
            if _stages_too_similar(stage0, stage1):
                rejected.append(
                    {
                        "propellant": prop_spec.name,
                        "reason": "stage_metrics_too_similar",
                        "split_ratio": f"{split:.2f}",
                    }
                )
                continue
            if _stages_too_similar(stage0, stage1):
                rejected.append(
                    {
                        "propellant": prop_spec.name,
                        "reason": "stage_metrics_too_similar",
                        "split_ratio": f"{split:.2f}",
                    }
                )
                continue

            stage0_len = _stage_length_in(stage0.spec)
            stage1_len = _stage_length_in(stage1.spec)
            if stage0_len + stage1_len > constraints.max_vehicle_length_in * (1.0 + _VEHICLE_DIM_TOLERANCE_PCT):
                rejected.append({"propellant": prop_spec.name, "reason": "motor stack exceeds vehicle length"})
                continue
            length_ratio = max(stage0_len, stage1_len) / max(min(stage0_len, stage1_len), 1e-6)
            if length_ratio > max(constraints.max_stage_length_ratio, _RELAXED_STAGE_LENGTH_RATIO):
                rejected.append({"propellant": prop_spec.name, "reason": "stage lengths differ too much"})
                continue

            try:
                if not rkt_path:
                    raise RuntimeError("rkt_path required for trajectory")
                total_mass_for_sim = (
                    _total_mass_from_dry(total_mass_kg, stage0.metrics, stage1.metrics)
                    if total_mass_kg is not None
                    else None
                )
                apogee = simulate_two_stage_apogee(
                    stage0=stage0.spec,
                    stage1=stage1.spec,
                    rkt_path=rkt_path,
                    cd_max=cd_max,
                    mach_max=mach_max,
                    cd_ramp=cd_ramp,
                    total_mass_kg=total_mass_for_sim,
                    separation_delay_s=separation_delay_s,
                    ignition_delay_s=ignition_delay_s,
                )
            except Exception as exc:
                rejected.append(
                    {"propellant": prop_spec.name, "reason": "simulation_failed", "detail": str(exc)}
                )
                continue
            if not (apogee.apogee_m == apogee.apogee_m and apogee.max_velocity_m_s == apogee.max_velocity_m_s):
                rejected.append(
                    {
                        "propellant": prop_spec.name,
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
                rejected.append({"propellant": prop_spec.name, "reason": "no_objectives_provided"})
                continue
            within_tolerance = bool(error <= targets.tolerance_pct)
            if not within_tolerance:
                rejected.append(
                    {
                        "propellant": prop_spec.name,
                        "reason": "objective_outside_tolerance",
                        "detail": f"error_pct={error * 100.0:.2f}",
                    }
                )

            prefix = f"mission_{_slugify_name(prop_spec.name)}_{int(split * 100)}"
            generate_two_stage_designs(
                base_ric_path=base_ric_path,
                output_dir=str(output_root),
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

            stage0_ric = output_root / f"{prefix}_stage0.ric"
            stage1_ric = output_root / f"{prefix}_stage1.ric"
            stage0_metrics = _stage_metrics_from_ric_or_spec(stage0, stage0_ric)
            stage1_metrics = _stage_metrics_from_ric_or_spec(stage1, stage1_ric)
            metrics = _combine_metric_dicts(stage0_metrics, stage1_metrics, constraints)
            metrics["max_velocity_m_s"] = apogee.max_velocity_m_s
            curve = _build_thrust_curve_from_ric_paths(
                stage0_ric, stage1_ric, separation_delay_s, ignition_delay_s
            )
            if not curve:
                curve = _build_thrust_curve(stage0, stage1, separation_delay_s, ignition_delay_s)
            vehicle_len = constraints.max_vehicle_length_in * (1.0 + _VEHICLE_DIM_TOLERANCE_PCT)
            stage_len = stage0_len + stage1_len
            stage_diameter = _stage_diameter_in(stage0.spec)
            name = f"{prop_spec.name} split {split:.2f}"
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
                    "name": name,
                    "propellant": prop_spec.name,
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
                    "candidate_key": _candidate_key(name, metrics, apogee.apogee_m * 3.28084),
                    "stage_metrics": {"stage0": stage0_metrics, "stage1": stage1_metrics},
                    "artifacts": {
                        "stage0_ric": str(stage0_ric),
                        "stage1_ric": str(stage1_ric),
                        "stage0_eng": str(output_root / f"{prefix}_stage0.eng"),
                        "stage1_eng": str(output_root / f"{prefix}_stage1.eng"),
                    },
                    "artifact_urls": {
                        "stage0_ric": _download_url(output_root, f"{prefix}_stage0.ric"),
                        "stage1_ric": _download_url(output_root, f"{prefix}_stage1.ric"),
                        "stage0_eng": _download_url(output_root, f"{prefix}_stage0.eng"),
                        "stage1_eng": _download_url(output_root, f"{prefix}_stage1.eng"),
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
    ranked = []
    for item in scored:
        log = _find_log_for_candidate(
            logs, item.candidate.name, item.candidate.metrics, item.candidate.apogee_ft
        )
        if log is None:
            log = _find_log_by_name_closest(logs, item.candidate.name, item.candidate.metrics)
        ranked.append(
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
                "stage_metrics": log.get("stage_metrics") if log else None,
                "artifacts": log.get("artifacts") if log else None,
                "artifact_urls": log.get("artifact_urls") if log else None,
            }
        )

    def _pressure_ok_entry(entry: dict[str, object]) -> bool:
        stage_metrics = entry.get("stage_metrics")
        if not isinstance(stage_metrics, dict):
            return False
        if stage_count == 1:
            return _pressure_within_tolerance(
                stage_metrics.get("stage0") or {}, constraints, tolerance_pct=0.01
            )
        return _pressure_within_tolerance(
            stage_metrics.get("stage0") or {}, constraints, tolerance_pct=0.01
        ) and _pressure_within_tolerance(
            stage_metrics.get("stage1") or {}, constraints, tolerance_pct=0.01
        )

    ranked = [entry for entry in ranked if _pressure_ok_entry(entry)]

    if _iteration < _max_iterations:
        best_entry = ranked[0] if ranked else None
        if targets.apogee_ft and best_entry:
            best_apogee = float(best_entry.get("apogee_ft") or 0.0)
            target_apogee = float(targets.apogee_ft)
            if best_apogee > 0 and best_apogee < target_apogee * (1.0 - targets.tolerance_pct):
                scale = (target_apogee / best_apogee) ** 0.5
                scale = max(1.1, min(scale, 2.2))
                if total_target_impulse_ns:
                    return mission_targeted_design_target_only(
                        output_dir=output_dir,
                        targets=targets,
                        constraints=constraints,
                        search=search,
                        split_ratios=split_ratios,
                        cd_max=cd_max,
                        mach_max=mach_max,
                        cd_ramp=cd_ramp,
                        total_mass_kg=total_mass_kg,
                        total_target_impulse_ns=total_target_impulse_ns * scale,
                        separation_delay_s=separation_delay_s,
                        ignition_delay_s=ignition_delay_s,
                        stage_count=stage_count,
                        velocity_calibration=velocity_calibration,
                        fast_mode=fast_mode,
                        vehicle_params=vehicle_params,
                        launch_altitude_m=launch_altitude_m,
                        wind_speed_m_s=wind_speed_m_s,
                        temperature_k=temperature_k,
                        rod_length_m=rod_length_m,
                        launch_angle_deg=launch_angle_deg,
                        ork_path=ork_path,
                        allowed_propellant_families=allowed_propellant_families,
                        allowed_propellant_names=allowed_propellant_names,
                        preset_path=preset_path,
                        weights=weights,
                        _iteration=_iteration + 1,
                        _max_iterations=_max_iterations,
                    )
        if not ranked:
            expanded = _expand_search_for_pressure(search)
            if expanded != search:
                return mission_targeted_design_target_only(
                    output_dir=output_dir,
                    targets=targets,
                    constraints=constraints,
                    search=expanded,
                    split_ratios=split_ratios,
                    cd_max=cd_max,
                    mach_max=mach_max,
                    cd_ramp=cd_ramp,
                    total_mass_kg=total_mass_kg,
                    total_target_impulse_ns=total_target_impulse_ns,
                    separation_delay_s=separation_delay_s,
                    ignition_delay_s=ignition_delay_s,
                    stage_count=stage_count,
                    velocity_calibration=velocity_calibration,
                    fast_mode=fast_mode,
                    vehicle_params=vehicle_params,
                    launch_altitude_m=launch_altitude_m,
                    wind_speed_m_s=wind_speed_m_s,
                    temperature_k=temperature_k,
                    rod_length_m=rod_length_m,
                    launch_angle_deg=launch_angle_deg,
                    ork_path=ork_path,
                    allowed_propellant_families=allowed_propellant_families,
                    allowed_propellant_names=allowed_propellant_names,
                    preset_path=preset_path,
                    weights=weights,
                    _iteration=_iteration + 1,
                    _max_iterations=_max_iterations,
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


def _default_base_spec(vehicle_params: VehicleParams, propellant: PropellantSpec) -> MotorSpec:
    diameter = max(vehicle_params.ref_diameter_m * 0.9, 0.05)
    core = diameter * 0.2
    length = max(vehicle_params.ref_diameter_m * 1.5, 0.2)
    grains = [
        BATESGrain(
            diameter_m=diameter,
            core_diameter_m=core,
            length_m=length,
            inhibited_ends="Neither",
        )
        for _ in range(7)
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
    rod_length_m: float = 0.0,
    launch_angle_deg: float = 0.0,
    ork_path: str | None = None,
    allowed_propellant_families: list[str] | None = None,
    allowed_propellant_names: list[str] | None = None,
    preset_path: str | None = None,
    weights: ScoreWeights | None = None,
    stage0_length_in: float | None = None,
    stage1_length_in: float | None = None,
    _iteration: int = 0,
    _max_iterations: int = 7,
    progress_cb: Callable[[dict[str, object]], None] | None = None,
) -> dict[str, object]:
    propellant_specs = _load_propellant_specs(
        preset_path=preset_path,
        allowed_propellant_families=allowed_propellant_families,
        allowed_propellant_names=allowed_propellant_names,
    )
    effective_stage_ratio = max(constraints.max_stage_length_ratio, _RELAXED_STAGE_LENGTH_RATIO)

    if total_mass_kg is None or total_mass_kg <= 0:
        raise RuntimeError("total_mass_kg (dry mass) is required for target-only runs.")
    dry_mass_kg = total_mass_kg

    seed_prop = propellant_specs[0]
    base_spec = _default_base_spec(vehicle_params, seed_prop)

    out_dir = _resolve_output_dir(output_dir)
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
                rod_length_m=rod_length_m,
                launch_angle_deg=launch_angle_deg,
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
                rod_length_m=rod_length_m,
                launch_angle_deg=launch_angle_deg,
            )

    # Replace grid search with SmartNozzleArchitect volume-first search.
    architect = SmartNozzleArchitect()
    winners: list[dict[str, object]] = []
    rejected: list[dict[str, str]] = []
    max_length_in = constraints.max_vehicle_length_in * (1.0 + _VEHICLE_DIM_TOLERANCE_PCT)
    stage_length_tolerance_in = 6.0
    stage0_target_in = stage0_length_in if stage0_length_in and stage0_length_in > 0 else None
    stage1_target_in = stage1_length_in if stage1_length_in and stage1_length_in > 0 else None

    def _rocket_dims_for(target_in: float | None) -> dict[str, float]:
        max_len = max_length_in
        if target_in is not None:
            max_len = min(max_len, target_in + stage_length_tolerance_in)
        return {
            "diameter": vehicle_params.ref_diameter_m * 39.3701,
            "max_length": max_len,
        }

    rocket_dims = _rocket_dims_for(stage0_target_in)
    rocket_dims_stage1 = _rocket_dims_for(stage1_target_in)
    stage_specific_lengths = stage_count == 2 and (stage0_target_in is not None or stage1_target_in is not None)
    dry_mass_lbs = dry_mass_kg * 2.20462
    class_thresholds: list[float] = []
    try:
        class_solution = calculate_motor_requirements(
            ClassificationRequest(
                target_apogee_ft=targets.apogee_ft or 0.0,
                dry_mass_lbs=dry_mass_lbs,
                diameter_in=vehicle_params.ref_diameter_m * 39.3701,
                num_stages=stage_count,
            )
        )
        class_thresholds = [
            stage.class_ceiling_ns * 0.99 for stage in class_solution.stages
        ]
    except Exception:
        class_thresholds = []

    def _stage_threshold(idx: int) -> float | None:
        if not class_thresholds:
            return None
        if idx < len(class_thresholds):
            return class_thresholds[idx]
        return class_thresholds[-1]

    pressure_limit = constraints.max_pressure_psi * 1.06
    kn_limit = constraints.max_kn * 1.06

    for prop_spec in propellant_specs:
        try:
            if stage_count == 1:
                def _simulate_apogee(spec: MotorSpec, metrics: dict[str, float]):
                    total_mass_for_sim = _total_mass_from_dry(dry_mass_kg, metrics)
                    return simulate_single_stage_apogee_params(
                        stage=spec,
                        ref_diameter_m=vehicle_params.ref_diameter_m,
                        total_mass_kg=total_mass_for_sim,
                        cd_max=cd_max,
                        mach_max=mach_max,
                        cd_ramp=cd_ramp,
                        launch_altitude_m=launch_altitude_m,
                        wind_speed_m_s=wind_speed_m_s,
                        temperature_k=temperature_k,
                        rod_length_m=rod_length_m,
                        launch_angle_deg=launch_angle_deg,
                    )
                results = architect.find_optimal_motor(
                    target_apogee_ft=targets.apogee_ft,
                    dry_mass_lbs=dry_mass_lbs,
                    max_pressure_psi=constraints.max_pressure_psi,
                    rocket_dims=rocket_dims,
                    propellant=prop_spec,
                    base_spec=base_spec,
                    simulate_apogee=_simulate_apogee,
                    required_impulse_ns=total_target_impulse_ns,
                    progress_cb=progress_cb,
                    stage_length_target_in=stage0_target_in,
                    stage_length_tolerance_in=stage_length_tolerance_in,
                    max_checks=1500,
                )
            else:
                def _simulate_apogee(spec: MotorSpec, metrics: dict[str, float]):
                    prop_mass = metrics.get("propellant_mass", 0.0)
                    total_mass_for_sim = max(dry_mass_kg + (prop_mass * 2.0), 1e-6)
                    stage0_dry, stage1_dry = _split_stage_dry_masses(
                        total_mass_for_sim, prop_mass, prop_mass
                    )
                    return simulate_two_stage_apogee_params(
                        stage0=spec,
                        stage1=spec,
                        ref_diameter_m=vehicle_params.ref_diameter_m,
                        stage0_dry_kg=stage0_dry,
                        stage1_dry_kg=stage1_dry,
                        cd_max=cd_max,
                        mach_max=mach_max,
                        cd_ramp=cd_ramp,
                        separation_delay_s=separation_delay_s,
                        ignition_delay_s=ignition_delay_s,
                        total_mass_kg=None,
                        launch_altitude_m=launch_altitude_m,
                        wind_speed_m_s=wind_speed_m_s,
                        temperature_k=temperature_k,
                        rod_length_m=rod_length_m,
                        launch_angle_deg=launch_angle_deg,
                    )
                if stage_specific_lengths:
                    split_ratio = split_ratios[0] if split_ratios else 0.5
                    stage0_impulse = (
                        total_target_impulse_ns * split_ratio
                        if total_target_impulse_ns
                        else None
                    )
                    stage1_impulse = (
                        total_target_impulse_ns * (1.0 - split_ratio)
                        if total_target_impulse_ns
                        else None
                    )

                    def _progress_stage(stage_label: str):
                        def _cb(payload: dict[str, object]) -> None:
                            if progress_cb:
                                progress_cb({**payload, "stage": stage_label})
                        return _cb

                    stage0_results = architect.find_optimal_motor(
                        target_apogee_ft=targets.apogee_ft,
                        dry_mass_lbs=dry_mass_lbs,
                        max_pressure_psi=constraints.max_pressure_psi,
                        rocket_dims=rocket_dims,
                        propellant=prop_spec,
                        base_spec=base_spec,
                        simulate_apogee=_simulate_apogee,
                        required_impulse_ns=stage0_impulse,
                        progress_cb=_progress_stage("stage0"),
                        stage_length_target_in=stage0_target_in,
                        stage_length_tolerance_in=stage_length_tolerance_in,
                        max_checks=1500,
                    )
                    if not stage0_results:
                        rejected.append(
                            {
                                "propellant": prop_spec.name,
                                "reason": "no_stage0_winner",
                            }
                        )
                        continue
                    stage0_baseline = float(
                        stage0_results[0].metrics.get("total_impulse", 0.0) or 0.0
                    )
                    stage1_baseline = stage0_baseline * 1.5 if stage0_baseline > 0 else stage1_impulse
                    stage1_results = architect.find_optimal_motor(
                        target_apogee_ft=targets.apogee_ft,
                        dry_mass_lbs=dry_mass_lbs,
                        max_pressure_psi=constraints.max_pressure_psi,
                        rocket_dims=rocket_dims_stage1,
                        propellant=prop_spec,
                        base_spec=base_spec,
                        simulate_apogee=_simulate_apogee,
                        required_impulse_ns=stage1_baseline,
                        progress_cb=_progress_stage("stage1"),
                        stage_length_target_in=stage1_target_in,
                        stage_length_tolerance_in=stage_length_tolerance_in,
                        max_checks=1500,
                    )
                    if stage0_results and stage1_results:
                        winners.append(
                            {
                                "propellant": prop_spec.name,
                                "stage0": stage0_results[0],
                                "stage1": stage1_results[0],
                                "split_ratio": split_ratio,
                            }
                        )
                    else:
                        rejected.append(
                            {
                                "propellant": prop_spec.name,
                                "reason": "no_stage_pair",
                            }
                        )
                    continue
                results = architect.find_optimal_motor(
                    target_apogee_ft=targets.apogee_ft,
                    dry_mass_lbs=dry_mass_lbs,
                    max_pressure_psi=constraints.max_pressure_psi,
                    rocket_dims=rocket_dims,
                    propellant=prop_spec,
                    base_spec=base_spec,
                    simulate_apogee=_simulate_apogee,
                    required_impulse_ns=total_target_impulse_ns,
                    progress_cb=progress_cb,
                    stage_length_target_in=stage0_target_in,
                    stage_length_tolerance_in=stage_length_tolerance_in,
                    max_checks=1500,
                )
        except Exception as exc:
            rejected.append({"propellant": prop_spec.name, "reason": str(exc)})
            continue
        for result in results:
            winners.append({"propellant": prop_spec.name, "result": result})

    if not winners:
        # Fallback: return a baseline candidate to avoid empty UI.
        try:
            _, base_metrics = simulate_motorlib_with_result(base_spec)
            fallback_candidate = Candidate(
                name=f"{seed_prop.name} baseline",
                metrics=_single_stage_metric_dict(base_metrics, constraints),
                thrust_curve=None,
                apogee_ft=None,
                vehicle_length_in=vehicle_params.rocket_length_in,
                stage_length_in=_stage_length_in(base_spec),
                stage_diameter_in=_stage_diameter_in(base_spec),
            )
            logs = [
                {
                    "name": fallback_candidate.name,
                    "propellant": seed_prop.name,
                    "apogee_ft": None,
                    "max_velocity_m_s": None,
                    "objective_reports": [],
                    "objective_error_pct": None,
                    "within_tolerance": False,
                    "metrics": fallback_candidate.metrics,
                    "stage_metrics": {"stage0": base_metrics},
                    "artifacts": None,
                    "artifact_urls": None,
                    "status": "partial",
                    "reason": "no_viable_candidates",
                }
            ]
            ranked = [
                {
                    "name": fallback_candidate.name,
                    "apogee_ft": None,
                    "metrics": fallback_candidate.metrics,
                    "objective_reports": [],
                    "stage_metrics": {"stage0": base_metrics},
                    "artifacts": None,
                    "artifact_urls": None,
                }
            ]
            return _json_safe(
                {
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
                        "candidate_count": 1,
                        "viable_count": 0,
                        "rejected_count": len(rejected),
                    },
                    "openrocket": None,
                    "candidates": logs,
                    "ranked": ranked,
                    "rejected": rejected,
                }
            )
        except Exception:
            return _json_safe(
                {
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
                        "candidate_count": 0,
                        "viable_count": 0,
                        "rejected_count": len(rejected),
                    },
                    "openrocket": None,
                    "candidates": [],
                    "ranked": [],
                    "rejected": rejected,
                }
            )

    if stage_specific_lengths:
        winners.sort(
            key=lambda item: (
                (item["stage0"].stage_length_in + item["stage1"].stage_length_in),
            )
        )
    else:
        winners.sort(
            key=lambda item: (
                abs(item["result"].apogee_ft - targets.apogee_ft),
                item["result"].stage_length_in,
            )
        )

    all_candidates: list[Candidate] = []
    viable_candidates: list[Candidate] = []
    logs: list[dict[str, object]] = []
    ranked: list[dict[str, object]] = []
    winners_per_propellant: dict[str, int] = {}
    best_fail_score = float("inf")
    best_fail_candidate: Candidate | None = None
    best_fail_log: dict[str, object] | None = None

    for idx, item in enumerate(winners):
        result = item.get("result") if isinstance(item, dict) else None
        prop_name = item["propellant"]
        if stage_count == 1:
            prefix = f"mission_{_slugify_name(prop_name)}_{idx}"
            steps, _ = simulate_motorlib_with_result(result.spec)
            eng = build_eng(result.spec, steps, designation=prefix, manufacturer="openmotor-ai")
            ric_out = out_dir / f"{prefix}.ric"
            eng_out = out_dir / f"{prefix}.eng"
            ric_out.write_text(build_ric(result.spec), encoding="utf-8")
            eng_out.write_text(export_eng(eng), encoding="utf-8")
            stage_result = StageResult(spec=result.spec, metrics=result.metrics, log={})
            stage_metrics = _stage_metrics_from_ric_or_spec(stage_result, ric_out)
            metrics = _single_stage_metric_dict(stage_metrics, constraints)
            metrics["max_velocity_m_s"] = result.max_velocity_m_s
            curve = _build_single_stage_thrust_curve_from_ric(ric_out)
            if not curve:
                curve = _build_single_stage_thrust_curve(stage_result)
            candidate = Candidate(
                name=result.name,
                metrics=metrics,
                thrust_curve=curve,
                apogee_ft=result.apogee_ft,
                vehicle_length_in=vehicle_params.rocket_length_in,
                stage_length_in=result.stage_length_in,
                stage_diameter_in=result.stage_diameter_in,
            )
            artifacts = {"ric": str(ric_out), "eng": str(eng_out)}
            artifact_urls = {
                "ric": _download_url(out_dir, ric_out.name),
                "eng": _download_url(out_dir, eng_out.name),
            }
            stage_metrics_payload = {"stage0": stage_metrics}
        else:
            prefix = f"mission_{_slugify_name(prop_name)}_{idx}"
            stage0_ric_out = out_dir / f"{prefix}_stage0.ric"
            stage1_ric_out = out_dir / f"{prefix}_stage1.ric"
            stage0_eng_out = out_dir / f"{prefix}_stage0.eng"
            stage1_eng_out = out_dir / f"{prefix}_stage1.eng"

            if stage_specific_lengths and "stage0" in item and "stage1" in item:
                stage0_result = item["stage0"]
                stage1_result = item["stage1"]
                steps0, _ = simulate_motorlib_with_result(stage0_result.spec)
                steps1, _ = simulate_motorlib_with_result(stage1_result.spec)
                eng0 = build_eng(
                    stage0_result.spec,
                    steps0,
                    designation=f"{prefix}-S0",
                    manufacturer="openmotor-ai",
                )
                eng1 = build_eng(
                    stage1_result.spec,
                    steps1,
                    designation=f"{prefix}-S1",
                    manufacturer="openmotor-ai",
                )
                stage0_ric_out.write_text(build_ric(stage0_result.spec), encoding="utf-8")
                stage1_ric_out.write_text(build_ric(stage1_result.spec), encoding="utf-8")
                stage0_eng_out.write_text(export_eng(eng0), encoding="utf-8")
                stage1_eng_out.write_text(export_eng(eng1), encoding="utf-8")
                stage0 = StageResult(spec=stage0_result.spec, metrics=stage0_result.metrics, log={})
                stage1 = StageResult(spec=stage1_result.spec, metrics=stage1_result.metrics, log={})
                stage0_metrics = _stage_metrics_from_ric_or_spec(stage0, stage0_ric_out)
                stage1_metrics = _stage_metrics_from_ric_or_spec(stage1, stage1_ric_out)
                metrics = _combine_metric_dicts(stage0_metrics, stage1_metrics, constraints)
                curve = _build_thrust_curve_from_ric_paths(
                    stage0_ric_out, stage1_ric_out, separation_delay_s, ignition_delay_s
                )
                if not curve:
                    curve = _build_thrust_curve(stage0, stage1, separation_delay_s, ignition_delay_s)
                apogee_ft = None
                max_velocity_m_s = None
                try:
                    total_mass_for_sim = _total_mass_from_dry(
                        dry_mass_kg, stage0_metrics, stage1_metrics
                    )
                    prop0 = float(stage0_metrics.get("propellant_mass", 0.0) or 0.0)
                    prop1 = float(stage1_metrics.get("propellant_mass", 0.0) or 0.0)
                    stage0_dry, stage1_dry = _split_stage_dry_masses(
                        total_mass_for_sim, prop0, prop1
                    )
                    apogee = simulate_two_stage_apogee_params(
                        stage0=stage0_result.spec,
                        stage1=stage1_result.spec,
                        ref_diameter_m=vehicle_params.ref_diameter_m,
                        stage0_dry_kg=stage0_dry,
                        stage1_dry_kg=stage1_dry,
                        cd_max=cd_max,
                        mach_max=mach_max,
                        cd_ramp=cd_ramp,
                        separation_delay_s=separation_delay_s,
                        ignition_delay_s=ignition_delay_s,
                        total_mass_kg=None,
                        launch_altitude_m=launch_altitude_m,
                        wind_speed_m_s=wind_speed_m_s,
                        temperature_k=temperature_k,
                        rod_length_m=rod_length_m,
                        launch_angle_deg=launch_angle_deg,
                    )
                    apogee_ft = apogee.apogee_m * 3.28084
                    max_velocity_m_s = apogee.max_velocity_m_s
                except Exception:
                    apogee_ft = None
                    max_velocity_m_s = None
                metrics["max_velocity_m_s"] = max_velocity_m_s
                candidate = Candidate(
                    name=f"{prop_name} stage-pair",
                    metrics=metrics,
                    thrust_curve=curve,
                    apogee_ft=apogee_ft,
                    vehicle_length_in=vehicle_params.rocket_length_in,
                    stage_length_in=stage0_result.stage_length_in + stage1_result.stage_length_in,
                    stage_diameter_in=max(
                        stage0_result.stage_diameter_in, stage1_result.stage_diameter_in
                    ),
                )
                artifacts = {
                    "stage0_ric": str(stage0_ric_out),
                    "stage1_ric": str(stage1_ric_out),
                    "stage0_eng": str(stage0_eng_out),
                    "stage1_eng": str(stage1_eng_out),
                }
                artifact_urls = {
                    "stage0_ric": _download_url(out_dir, stage0_ric_out.name),
                    "stage1_ric": _download_url(out_dir, stage1_ric_out.name),
                    "stage0_eng": _download_url(out_dir, stage0_eng_out.name),
                    "stage1_eng": _download_url(out_dir, stage1_eng_out.name),
                }
                stage_metrics_payload = {"stage0": stage0_metrics, "stage1": stage1_metrics}
            else:
                steps0, _ = simulate_motorlib_with_result(result.spec)
                steps1, _ = simulate_motorlib_with_result(result.spec)
                eng0 = build_eng(
                    result.spec, steps0, designation=f"{prefix}-S0", manufacturer="openmotor-ai"
                )
                eng1 = build_eng(
                    result.spec, steps1, designation=f"{prefix}-S1", manufacturer="openmotor-ai"
                )
                stage0_ric_out.write_text(build_ric(result.spec), encoding="utf-8")
                stage1_ric_out.write_text(build_ric(result.spec), encoding="utf-8")
                stage0_eng_out.write_text(export_eng(eng0), encoding="utf-8")
                stage1_eng_out.write_text(export_eng(eng1), encoding="utf-8")
                stage0 = StageResult(spec=result.spec, metrics=result.metrics, log={})
                stage1 = StageResult(spec=result.spec, metrics=result.metrics, log={})
                stage0_metrics = _stage_metrics_from_ric_or_spec(stage0, stage0_ric_out)
                stage1_metrics = _stage_metrics_from_ric_or_spec(stage1, stage1_ric_out)
                metrics = _combine_metric_dicts(stage0_metrics, stage1_metrics, constraints)
                metrics["max_velocity_m_s"] = result.max_velocity_m_s
                curve = _build_thrust_curve_from_ric_paths(
                    stage0_ric_out, stage1_ric_out, separation_delay_s, ignition_delay_s
                )
                if not curve:
                    curve = _build_thrust_curve(stage0, stage1, separation_delay_s, ignition_delay_s)
                candidate = Candidate(
                    name=result.name,
                    metrics=metrics,
                    thrust_curve=curve,
                    apogee_ft=result.apogee_ft,
                    vehicle_length_in=vehicle_params.rocket_length_in,
                    stage_length_in=result.stage_length_in,
                    stage_diameter_in=result.stage_diameter_in,
                )
                artifacts = {
                    "stage0_ric": str(stage0_ric_out),
                    "stage1_ric": str(stage1_ric_out),
                    "stage0_eng": str(stage0_eng_out),
                    "stage1_eng": str(stage1_eng_out),
                }
                artifact_urls = {
                    "stage0_ric": _download_url(out_dir, stage0_ric_out.name),
                    "stage1_ric": _download_url(out_dir, stage1_ric_out.name),
                    "stage0_eng": _download_url(out_dir, stage0_eng_out.name),
                    "stage1_eng": _download_url(out_dir, stage1_eng_out.name),
                }
                stage_metrics_payload = {"stage0": stage0_metrics, "stage1": stage1_metrics}

        max_velocity_value = float(metrics.get("max_velocity_m_s", 0.0) or 0.0)
        apogee_value = float(candidate.apogee_ft or 0.0)
        def _stage_ok(stage_metrics: dict[str, float], idx: int) -> bool:
            threshold = _stage_threshold(idx)
            total_impulse = float(stage_metrics.get("total_impulse", 0.0) or 0.0)
            if threshold is not None and total_impulse < threshold:
                return False
            peak_pressure_psi = float(stage_metrics.get("peak_chamber_pressure", 0.0) or 0.0) / 6894.757
            if peak_pressure_psi > pressure_limit:
                return False
            peak_kn = float(stage_metrics.get("peak_kn", 0.0) or 0.0)
            if peak_kn > kn_limit:
                return False
            return True

        def _stage_distance(stage_metrics: dict[str, float], idx: int) -> float:
            distance = 0.0
            threshold = _stage_threshold(idx)
            total_impulse = float(stage_metrics.get("total_impulse", 0.0) or 0.0)
            if threshold is not None and threshold > 0:
                deficit = max(0.0, threshold - total_impulse)
                distance += deficit / threshold
            peak_pressure_psi = float(stage_metrics.get("peak_chamber_pressure", 0.0) or 0.0) / 6894.757
            if pressure_limit > 0:
                distance += max(0.0, peak_pressure_psi - pressure_limit) / pressure_limit
            peak_kn = float(stage_metrics.get("peak_kn", 0.0) or 0.0)
            if kn_limit > 0:
                distance += max(0.0, peak_kn - kn_limit) / kn_limit
            return distance

        stage_metrics_list: list[dict[str, float]] = []
        if stage_count == 1:
            stage_metrics_list = [stage_metrics]
        else:
            stage_metrics_list = [
                stage_metrics_payload.get("stage0") or {},
                stage_metrics_payload.get("stage1") or {},
            ]
        error = _objective_error_pct(
            apogee_value,
            max_velocity_value,
            targets.apogee_ft,
            targets.max_velocity_m_s,
        )
        if not all(_stage_ok(sm, idx) for idx, sm in enumerate(stage_metrics_list)):
            distance = sum(
                _stage_distance(sm, idx) for idx, sm in enumerate(stage_metrics_list)
            )
            if distance < best_fail_score:
                best_fail_score = distance
                best_fail_candidate = candidate
                best_fail_log = {
                    "name": candidate.name,
                    "propellant": prop_name,
                    "apogee_ft": candidate.apogee_ft,
                    "max_velocity_m_s": max_velocity_value,
                    "objective_reports": _objective_reports(
                        candidate.apogee_ft,
                        max_velocity_value,
                        targets.apogee_ft,
                        targets.max_velocity_m_s,
                    ),
                    "objective_error_pct": float(error * 100.0) if error is not None else None,
                    "within_tolerance": False,
                    "metrics": candidate.metrics,
                    "stage_metrics": stage_metrics_payload,
                    "artifacts": artifacts,
                    "artifact_urls": artifact_urls,
                    "status": "partial",
                    "reason": "closest_fail",
                }
            continue

        prop_count = winners_per_propellant.get(prop_name, 0)
        if prop_count >= 6:
            continue
        within_tolerance = bool(error is not None and error <= targets.tolerance_pct)

        winners_per_propellant[prop_name] = prop_count + 1
        all_candidates.append(candidate)
        if within_tolerance:
            viable_candidates.append(candidate)

        log_entry = {
            "name": candidate.name,
            "propellant": prop_name,
            "apogee_ft": candidate.apogee_ft,
            "max_velocity_m_s": max_velocity_value,
            "objective_reports": _objective_reports(
                candidate.apogee_ft,
                max_velocity_value,
                targets.apogee_ft,
                targets.max_velocity_m_s,
            ),
            "objective_error_pct": float(error * 100.0) if error is not None else None,
            "within_tolerance": within_tolerance,
            "metrics": candidate.metrics,
            "stage_metrics": stage_metrics_payload,
            "artifacts": artifacts,
            "artifact_urls": artifact_urls,
        }
        logs.append(log_entry)
        ranked.append(
            {
                "name": candidate.name,
                "apogee_ft": candidate.apogee_ft,
                "metrics": candidate.metrics,
                "objective_reports": log_entry["objective_reports"],
                "objective_error_pct": log_entry["objective_error_pct"],
                "stage_metrics": stage_metrics_payload,
                "artifacts": artifacts,
                "artifact_urls": artifact_urls,
            }
        )

    ranked.sort(
        key=lambda entry: (
            entry.get("objective_error_pct") is None,
            entry.get("objective_error_pct") or float("inf"),
        )
    )

    if not all_candidates and best_fail_candidate and best_fail_log:
        all_candidates.append(best_fail_candidate)
        logs.append(best_fail_log)
        ranked.append(
            {
                "name": best_fail_candidate.name,
                "apogee_ft": best_fail_candidate.apogee_ft,
                "metrics": best_fail_candidate.metrics,
                "objective_reports": best_fail_log.get("objective_reports"),
                "objective_error_pct": best_fail_log.get("objective_error_pct"),
                "stage_metrics": best_fail_log.get("stage_metrics"),
                "artifacts": best_fail_log.get("artifacts"),
                "artifact_urls": best_fail_log.get("artifact_urls"),
            }
        )

    return _json_safe(
        {
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
            "openrocket": None,
            "candidates": logs,
            "ranked": ranked,
            "rejected": rejected,
        }
    )

    viable_candidates: list[Candidate] = []
    all_candidates: list[Candidate] = []
    logs: list[dict[str, object]] = []
    rejected: list[dict[str, str]] = []
    stage_cache: dict[tuple[object, ...], StageResult | None] = {}

    for prop_spec in propellant_specs:
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
                    reject_context={"propellant": prop_spec.name},
                    cache=stage_cache,
                )
            except Exception as exc:
                rejected.append({"propellant": prop_spec.name, "reason": str(exc)})
                continue
            if not grid:
                rejected.append({"propellant": prop_spec.name, "reason": "no_feasible_stage"})
                continue
            top_k = 3 if fast_mode else 5
            ranked = sorted(
                grid,
                key=lambda stage: abs(stage.metrics["total_impulse"] - total_target_impulse_ns),
            )[:top_k]
            best_stage = None
            best_stage_metrics = None
            best_apogee = None
            best_error = None
            for idx, stage in enumerate(ranked):
                stage_len = _stage_length_in(stage.spec)
                if stage_len > constraints.max_vehicle_length_in * (1.0 + _VEHICLE_DIM_TOLERANCE_PCT):
                    continue
                try:
                    temp_ric = out_dir / f"_candidate_{_slugify_name(prop_spec.name)}_{idx}.ric"
                    temp_ric.write_text(build_ric(stage.spec), encoding="utf-8")
                    stage_metrics = _stage_metrics_from_ric_or_spec(stage, temp_ric)
                    if not _pressure_within_tolerance(stage_metrics, constraints, tolerance_pct=0.01):
                        rejected.append(
                            {
                                "propellant": prop_spec.name,
                                "reason": "pressure_outside_tolerance",
                                "detail": "single_stage_peak_pressure",
                            }
                        )
                        continue
                    total_mass_for_sim = _total_mass_from_dry(dry_mass_kg, stage_metrics)
                    apogee = simulate_single_stage_apogee_params(
                        stage=stage.spec,
                        ref_diameter_m=vehicle_params.ref_diameter_m,
                        total_mass_kg=total_mass_for_sim,
                        cd_max=cd_max,
                        mach_max=mach_max,
                        cd_ramp=cd_ramp,
                        launch_altitude_m=launch_altitude_m,
                        wind_speed_m_s=wind_speed_m_s,
                        temperature_k=temperature_k,
                        rod_length_m=rod_length_m,
                        launch_angle_deg=launch_angle_deg,
                    )
                except Exception as exc:
                    rejected.append(
                        {"propellant": prop_spec.name, "reason": "simulation_failed", "detail": str(exc)}
                    )
                    continue
                if not (
                    apogee.apogee_m == apogee.apogee_m
                    and apogee.max_velocity_m_s == apogee.max_velocity_m_s
                ):
                    rejected.append(
                        {
                            "propellant": prop_spec.name,
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
                    rejected.append({"propellant": prop_spec.name, "reason": "no_objectives_provided"})
                    continue
                if best_error is None or error < best_error:
                    best_error = error
                    best_stage = stage
                    best_stage_metrics = stage_metrics
                    best_apogee = apogee
            if best_stage is None or best_apogee is None or best_error is None:
                rejected.append({"propellant": prop_spec.name, "reason": "no_viable_simulation"})
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
                        "propellant": prop_spec.name,
                        "reason": "objective_outside_tolerance",
                        "detail": f"error_pct={best_error * 100.0:.2f}",
                    }
                )

            prefix = f"mission_{_slugify_name(prop_spec.name)}"
            steps, _ = simulate_motorlib_with_result(best_stage.spec)
            eng = build_eng(best_stage.spec, steps, designation=prefix, manufacturer="openmotor-ai")
            ric_out = out_dir / f"{prefix}.ric"
            eng_out = out_dir / f"{prefix}.eng"
            ric_out.write_text(build_ric(best_stage.spec), encoding="utf-8")
            eng_out.write_text(export_eng(eng), encoding="utf-8")

            stage_metrics = best_stage_metrics or _stage_metrics_from_ric_or_spec(best_stage, ric_out)
            metrics = _single_stage_metric_dict(stage_metrics, constraints)
            metrics["max_velocity_m_s"] = calibrated_velocity
            curve = _build_single_stage_thrust_curve_from_ric(ric_out)
            if not curve:
                curve = _build_single_stage_thrust_curve(best_stage)
            vehicle_len = vehicle_params.rocket_length_in
            stage_diameter = _stage_diameter_in(best_stage.spec)
            name = f"{prop_spec.name} single stage"
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
                    "name": name,
                    "propellant": prop_spec.name,
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
                    "candidate_key": _candidate_key(name, metrics, best_apogee.apogee_m * 3.28084),
                    "stage_metrics": {"stage0": stage_metrics},
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
                    reject_context={"propellant": prop_spec.name},
                    cache=stage_cache,
                )
            except Exception as exc:
                rejected.append({"propellant": prop_spec.name, "reason": str(exc)})
                continue
            if not grid0:
                rejected.append({"propellant": prop_spec.name, "reason": "no_feasible_stage_pair"})
                continue
            grid_by_diameter = _group_grid_by_diameter(grid0)
            for split in split_ratios:
                stage0_target = total_target_impulse_ns * split
                stage1_target = total_target_impulse_ns * (1.0 - split)
                for diameter_key, grid_items in grid_by_diameter.items():
                    stage0 = _select_best_stage_for_target(grid_items, stage0_target)
                    stage1 = _select_best_stage_for_target(grid_items, stage1_target, exclude=stage0)
                    if stage0 is None or stage1 is None:
                        continue
                    if _stages_too_similar(stage0, stage1):
                        continue

                    stage0_len = _stage_length_in(stage0.spec)
                    stage1_len = _stage_length_in(stage1.spec)
                    if stage0_len + stage1_len > constraints.max_vehicle_length_in * (1.0 + _VEHICLE_DIM_TOLERANCE_PCT):
                        rejected.append(
                            {
                                "propellant": prop_spec.name,
                                "split_ratio": split,
                                "reason": "motor exceeds vehicle length",
                            }
                        )
                        continue

                    length_ratio = max(stage0_len, stage1_len) / max(min(stage0_len, stage1_len), 1e-6)
                    if length_ratio > effective_stage_ratio:
                        rejected.append(
                            {
                                "propellant": prop_spec.name,
                                "split_ratio": split,
                                "reason": "stage length ratio too large",
                            }
                        )
                        continue


                    try:
                        temp_stage0 = (
                            out_dir
                            / f"_candidate_{_slugify_name(prop_spec.name)}_{int(split * 100)}_{diameter_key}_s0.ric"
                        )
                        temp_stage1 = (
                            out_dir
                            / f"_candidate_{_slugify_name(prop_spec.name)}_{int(split * 100)}_{diameter_key}_s1.ric"
                        )
                        temp_stage0.write_text(build_ric(stage0.spec), encoding="utf-8")
                        temp_stage1.write_text(build_ric(stage1.spec), encoding="utf-8")
                        stage0_metrics = _stage_metrics_from_ric_or_spec(stage0, temp_stage0)
                        stage1_metrics = _stage_metrics_from_ric_or_spec(stage1, temp_stage1)
                        if not (
                            _pressure_within_tolerance(stage0_metrics, constraints, tolerance_pct=0.01)
                            and _pressure_within_tolerance(stage1_metrics, constraints, tolerance_pct=0.01)
                        ):
                            rejected.append(
                                {
                                    "propellant": prop_spec.name,
                                    "split_ratio": split,
                                    "reason": "pressure_outside_tolerance",
                                }
                            )
                            continue
                        total_mass_for_sim = _total_mass_from_dry(
                            dry_mass_kg, stage0_metrics, stage1_metrics
                        )
                        prop0 = stage0_metrics.get("propellant_mass", 0.0)
                        prop1 = stage1_metrics.get("propellant_mass", 0.0)
                        stage0_dry, stage1_dry = _split_stage_dry_masses(
                            total_mass_for_sim, prop0, prop1
                        )
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
                            total_mass_kg=None,
                            launch_altitude_m=launch_altitude_m,
                            wind_speed_m_s=wind_speed_m_s,
                            temperature_k=temperature_k,
                            rod_length_m=rod_length_m,
                            launch_angle_deg=launch_angle_deg,
                        )
                    except Exception as exc:
                        rejected.append(
                            {
                                "propellant": prop_spec.name,
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
                                "propellant": prop_spec.name,
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
                        rejected.append({"propellant": prop_spec.name, "reason": "no_objectives_provided"})
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
                                "propellant": prop_spec.name,
                                "split_ratio": split,
                                "reason": "objective_outside_tolerance",
                                "detail": f"error_pct={error * 100.0:.2f}",
                            }
                        )

                    prefix = f"mission_{_slugify_name(prop_spec.name)}_{int(split * 100)}"
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

                    stage0_metrics = _stage_metrics_from_ric_or_spec(stage0, stage0_ric_out)
                    stage1_metrics = _stage_metrics_from_ric_or_spec(stage1, stage1_ric_out)
                    metrics = _combine_metric_dicts(stage0_metrics, stage1_metrics, constraints)
                    metrics["max_velocity_m_s"] = calibrated_velocity
                    curve = _build_thrust_curve_from_ric_paths(
                        stage0_ric_out, stage1_ric_out, separation_delay_s, ignition_delay_s
                    )
                    if not curve:
                        curve = _build_thrust_curve(stage0, stage1, separation_delay_s, ignition_delay_s)
                    vehicle_len = vehicle_params.rocket_length_in
                    stage_diameter = _stage_diameter_in(stage0.spec)
                    name = f"{prop_spec.name} two stage"
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
                            "propellant": prop_spec.name,
                            "split_ratio": split,
                            "diameter_scale": diameter_key,
                            "stage0": stage0,
                            "stage1": stage1,
                            "error_pct": error,
                        }
                    logs.append(
                        {
                            "name": name,
                            "propellant": prop_spec.name,
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
                            "candidate_key": _candidate_key(name, metrics, apogee.apogee_m * 3.28084),
                            "stage_metrics": {"stage0": stage0_metrics, "stage1": stage1_metrics},
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
                    reject_context={"propellant": prop_spec.name, "refined": "stage0"},
                    cache=stage_cache,
                )
                grid1_refined = _build_stage_grid(
                    prop_base1,
                    refined_search1,
                    constraints,
                    reject_log=rejected,
                    reject_context={"propellant": prop_spec.name, "refined": "stage1"},
                    cache=stage_cache,
                )
                if grid0_refined and grid1_refined:
                    for split in refined_splits:
                        stage0_target = total_target_impulse_ns * split
                        stage1_target = total_target_impulse_ns * (1.0 - split)
                        stage0 = _select_best_stage_for_target(grid0_refined, stage0_target)
                        stage1 = _select_best_stage_for_target(grid1_refined, stage1_target, exclude=stage0)
                        if stage0 is None or stage1 is None:
                            continue
                        if _stages_too_similar(stage0, stage1):
                            continue
                        stage0_len = _stage_length_in(stage0.spec)
                        stage1_len = _stage_length_in(stage1.spec)
                        if stage0_len + stage1_len > constraints.max_vehicle_length_in * (1.0 + _VEHICLE_DIM_TOLERANCE_PCT):
                            continue
                        length_ratio = max(stage0_len, stage1_len) / max(
                            min(stage0_len, stage1_len), 1e-6
                        )
                        if length_ratio > effective_stage_ratio:
                            continue
                        try:
                            temp_stage0 = (
                                out_dir
                                / f"_candidate_{_slugify_name(prop_spec.name)}_{int(split * 100)}_refined_s0.ric"
                            )
                            temp_stage1 = (
                                out_dir
                                / f"_candidate_{_slugify_name(prop_spec.name)}_{int(split * 100)}_refined_s1.ric"
                            )
                            temp_stage0.write_text(build_ric(stage0.spec), encoding="utf-8")
                            temp_stage1.write_text(build_ric(stage1.spec), encoding="utf-8")
                            stage0_metrics = _stage_metrics_from_ric_or_spec(stage0, temp_stage0)
                            stage1_metrics = _stage_metrics_from_ric_or_spec(stage1, temp_stage1)
                            if not (
                                _pressure_within_tolerance(stage0_metrics, constraints, tolerance_pct=0.01)
                                and _pressure_within_tolerance(stage1_metrics, constraints, tolerance_pct=0.01)
                            ):
                                continue
                            total_mass_for_sim = _total_mass_from_dry(
                                dry_mass_kg, stage0_metrics, stage1_metrics
                            )
                            prop0 = stage0_metrics.get("propellant_mass", 0.0)
                            prop1 = stage1_metrics.get("propellant_mass", 0.0)
                            stage0_dry, stage1_dry = _split_stage_dry_masses(
                                total_mass_for_sim, prop0, prop1
                            )
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
                                total_mass_kg=None,
                                launch_altitude_m=launch_altitude_m,
                                wind_speed_m_s=wind_speed_m_s,
                                temperature_k=temperature_k,
                                rod_length_m=rod_length_m,
                                launch_angle_deg=launch_angle_deg,
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
                        prefix = f"mission_{_slugify_name(prop_spec.name)}_{int(split * 100)}"
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
                        stage0_metrics = _stage_metrics_from_ric_or_spec(stage0, stage0_ric_out)
                        stage1_metrics = _stage_metrics_from_ric_or_spec(stage1, stage1_ric_out)
                        metrics = _combine_metric_dicts(stage0_metrics, stage1_metrics, constraints)
                        metrics["max_velocity_m_s"] = calibrated_velocity
                        curve = _build_thrust_curve_from_ric_paths(
                            stage0_ric_out, stage1_ric_out, separation_delay_s, ignition_delay_s
                        )
                        if not curve:
                            curve = _build_thrust_curve(stage0, stage1, separation_delay_s, ignition_delay_s)
                        vehicle_len = vehicle_params.rocket_length_in
                        stage_diameter = _stage_diameter_in(stage0.spec)
                        name = f"{prop_spec.name} two stage"
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
                                "name": name,
                                "propellant": prop_spec.name,
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
                                "candidate_key": _candidate_key(name, metrics, apogee.apogee_m * 3.28084),
                                "stage_metrics": {"stage0": stage0_metrics, "stage1": stage1_metrics},
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

    openrocket_ranked = None
    if ork_path:
        from app.engine.openrocket.runner import run_openrocket_simulation

        scored_logs = []
        for log in logs:
            artifacts = log.get("artifacts") if isinstance(log, dict) else None
            if not isinstance(artifacts, dict):
                continue
            motor_paths: list[str] = []
            if artifacts.get("eng"):
                motor_paths.append(artifacts["eng"])
            else:
                if artifacts.get("stage0_eng"):
                    motor_paths.append(artifacts["stage0_eng"])
                if artifacts.get("stage1_eng"):
                    motor_paths.append(artifacts["stage1_eng"])
            if not motor_paths:
                continue
            try:
                or_result = run_openrocket_simulation(
                    {
                        "rocket_path": ork_path,
                        "motor_paths": motor_paths,
                        "stage_count": stage_count,
                        "separation_delay_s": separation_delay_s,
                        "ignition_delay_s": ignition_delay_s,
                        "launch_altitude_m": launch_altitude_m,
                        "wind_speed_m_s": wind_speed_m_s,
                        "temperature_k": temperature_k,
                        "rod_length_m": rod_length_m,
                        "launch_angle_deg": launch_angle_deg,
                    }
                )
            except Exception as exc:
                log["openrocket"] = {"status": "error", "detail": str(exc)}
                continue
            apogee_ft = float(or_result.get("apogee_m", 0.0)) * 3.28084
            max_v = or_result.get("max_velocity_m_s")
            error = _objective_error_pct_max(
                apogee_ft,
                max_v,
                targets.apogee_ft,
                targets.max_velocity_m_s,
            )
            log["openrocket"] = or_result | {
                "apogee_ft": apogee_ft,
                "objective_reports": _objective_reports(
                    apogee_ft,
                    max_v,
                    targets.apogee_ft,
                    targets.max_velocity_m_s,
                ),
                "objective_error_pct": float(error * 100.0) if error is not None else None,
            }
            if error is not None:
                scored_logs.append((error, log))
        if scored_logs:
            openrocket_ranked = [item for _, item in sorted(scored_logs, key=lambda item: item[0])]
            logs = openrocket_ranked

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
        log = _find_log_for_candidate(logs, item.name, item.metrics, item.apogee_ft)
        if log is None:
            log = _find_log_by_name_closest(logs, item.name, item.metrics)
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
                "stage_metrics": log.get("stage_metrics") if log else None,
                "artifacts": log.get("artifacts") if log else None,
                "artifact_urls": log.get("artifact_urls") if log else None,
            }
        )

    if openrocket_ranked:
        ranked = [
            {
                "name": item.get("name"),
                "apogee_ft": item.get("openrocket", {}).get("apogee_ft"),
                "metrics": item.get("metrics"),
                "objective_reports": item.get("openrocket", {}).get("objective_reports"),
                "openrocket": item.get("openrocket"),
                "stage_metrics": item.get("stage_metrics"),
                "artifacts": item.get("artifacts"),
                "artifact_urls": item.get("artifact_urls"),
            }
            for item in openrocket_ranked
            if isinstance(item, dict)
        ]

    if not ranked and logs:
        fallback_ranked = []
        for log in sorted(
            logs,
            key=lambda item: (item.get("objective_error_pct") or 1e9),
        ):
            if not isinstance(log, dict):
                continue
            fallback_ranked.append(
                {
                    "name": log.get("name"),
                    "apogee_ft": log.get("apogee_ft"),
                    "metrics": log.get("metrics"),
                    "objective_reports": log.get("objective_reports"),
                    "stage_metrics": log.get("stage_metrics"),
                    "artifacts": log.get("artifacts"),
                    "artifact_urls": log.get("artifact_urls"),
                }
            )
        ranked = fallback_ranked

    openrocket_eval = None
    if ork_path and ranked:
        try:
            best_name = ranked[0]["name"]
            best_log = next((log for log in logs if log.get("name") == best_name), None)
            if best_log and best_log.get("artifacts"):
                artifacts = best_log["artifacts"]
                motor_paths = []
                if artifacts.get("eng"):
                    motor_paths.append(artifacts["eng"])
                else:
                    if artifacts.get("stage0_eng"):
                        motor_paths.append(artifacts["stage0_eng"])
                    if artifacts.get("stage1_eng"):
                        motor_paths.append(artifacts["stage1_eng"])
                if motor_paths:
                    from app.engine.openrocket.runner import run_openrocket_simulation

                    openrocket_eval = run_openrocket_simulation(
                        {
                            "rocket_path": ork_path,
                            "motor_paths": motor_paths,
                            "stage_count": stage_count,
                            "separation_delay_s": separation_delay_s,
                            "ignition_delay_s": ignition_delay_s,
                            "launch_altitude_m": launch_altitude_m,
                            "wind_speed_m_s": wind_speed_m_s,
                            "temperature_k": temperature_k,
                            "rod_length_m": rod_length_m,
                            "launch_angle_deg": launch_angle_deg,
                        }
                    )
                    openrocket_eval["objective_reports"] = _objective_reports(
                        openrocket_eval.get("apogee_m", 0.0) * 3.28084,
                        openrocket_eval.get("max_velocity_m_s"),
                        targets.apogee_ft,
                        targets.max_velocity_m_s,
                    )
        except Exception as exc:
            openrocket_eval = {"status": "error", "detail": str(exc)}

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
        "openrocket": openrocket_eval,
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
    output_root = _resolve_output_dir(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "openmotor_ai_fit_metrics.json").write_text(
        __import__("json").dumps(best_log, indent=2),
        encoding="utf-8",
    )
    return best_log
