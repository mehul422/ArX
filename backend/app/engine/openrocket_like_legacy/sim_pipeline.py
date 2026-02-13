from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from app.engine.openmotor_ai.ballistics import TimeStep, aggregate_metrics
from app.engine.openmotor_ai.cdx1_reader import read_cdx1_dimensions
from app.engine.openmotor_ai.engine_versions import (
    openmotor_motorlib_version,
    trajectory_engine_version,
)
from app.engine.openmotor_ai.motorlib_adapter import (
    metrics_from_simresult,
    simulate_motorlib_with_result,
)
from app.engine.openmotor_ai.ork_reader import read_rocket_dimensions
from app.engine.openmotor_ai.propellant_library import load_preset_propellants
from app.engine.openmotor_ai.propellant_schema import PropellantSchema, propellant_to_spec
from app.engine.openmotor_ai.spec import BATESGrain, MotorConfig, MotorSpec, NozzleSpec, PropellantSpec
from app.engine.openmotor_ai.trajectory import simulate_two_stage_apogee
from app.engine.openrocket_like_legacy.artifacts import write_motor_artifacts
from app.engine.openrocket_like_legacy.constraints import evaluate_constraints
from app.engine.openrocket_like_legacy.grains import validate_grain_geometry
from app.engine.openrocket_like_legacy.models import (
    ConstraintSet,
    GrainGeometryType,
    MotorStageDefinition,
    ObjectiveReport,
)
from app.engine.openrocket_like_legacy.nozzle import validate_nozzle


@dataclass(frozen=True)
class StageSimulationResult:
    metrics: dict[str, float]
    steps: list[TimeStep]
    violations: list[str]
    engine: str


def _json_safe(value):
    if isinstance(value, Mapping):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "__dict__"):
        return _json_safe(value.__dict__)
    if hasattr(value, "value"):
        return value.value
    return value


def _compute_inputs_hash(payload: dict[str, object]) -> str:
    normalized = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _rocket_length_in(path: str) -> float | None:
    lower = path.lower()
    try:
        if lower.endswith(".ork"):
            return read_rocket_dimensions(path).length_m * 39.3701
        if lower.endswith(".cdx1"):
            return read_cdx1_dimensions(path).length_in
    except Exception:
        return None
    return None


def _load_preset_propellants() -> list[PropellantSchema]:
    root = Path(__file__).resolve().parents[3]
    presets_path = root / "resources" / "propellants" / "presets.json"
    return load_preset_propellants(str(presets_path))


def _resolve_propellant(stage: MotorStageDefinition) -> PropellantSpec:
    if stage.propellant_physics:
        schema = PropellantSchema.model_validate(stage.propellant_physics)
        return propellant_to_spec(schema)

    presets = _load_preset_propellants()
    for prop in presets:
        if prop.name.lower() == stage.propellant_label.name.lower():
            return propellant_to_spec(prop)
    raise ValueError(f"unknown propellant physics: {stage.propellant_label.name}")


def _build_motor_spec(stage: MotorStageDefinition) -> MotorSpec:
    validate_grain_geometry(stage.grain_geometry)
    validate_nozzle(stage.nozzle)
    if stage.grain_geometry.type != GrainGeometryType.BATES:
        raise ValueError(f"unsupported geometry for simulation: {stage.grain_geometry.type}")

    propellant = _resolve_propellant(stage)
    grain_count = int(stage.grain_geometry.params["grain_count"])
    grains = [
        BATESGrain(
            diameter_m=stage.grain_geometry.params["diameter_m"],
            core_diameter_m=stage.grain_geometry.params["core_diameter_m"],
            length_m=stage.grain_geometry.params["length_m"],
            inhibited_ends="Neither",
        )
        for _ in range(grain_count)
    ]
    nozzle = NozzleSpec(
        throat_diameter_m=stage.nozzle.throat_diameter_m,
        exit_diameter_m=stage.nozzle.exit_diameter_m,
        throat_length_m=stage.nozzle.throat_length_m,
        conv_angle_deg=stage.nozzle.conv_angle_deg,
        div_angle_deg=stage.nozzle.div_angle_deg,
        efficiency=stage.nozzle.efficiency,
        erosion_coeff=stage.nozzle.erosion_coeff,
        slag_coeff=stage.nozzle.slag_coeff,
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


def _simulate_stage(
    stage: MotorStageDefinition,
    constraints: ConstraintSet,
    out_dir: str,
    artifact_prefix: str,
    rocket_length_in: float | None,
) -> StageSimulationResult:
    spec = _build_motor_spec(stage)
    try:
        steps, sim = simulate_motorlib_with_result(spec)
        metrics = metrics_from_simresult(sim)
        engine = "motorlib"
    except Exception:
        steps = []
        metrics = aggregate_metrics(spec, steps)
        engine = "internal_fallback"
    violations = evaluate_constraints(metrics, constraints, rocket_length_in=rocket_length_in)
    if not metrics:
        violations.append("simulation_failed")
    write_motor_artifacts(
        spec=spec,
        steps=steps,
        out_dir=out_dir,
        prefix=artifact_prefix,
        propellant_label=stage.propellant_label.name,
    )
    return StageSimulationResult(
        metrics=metrics | {"simulation_engine": engine},
        steps=steps,
        violations=violations,
        engine=engine,
    )


def _objective_reports(
    apogee_ft: float | None,
    max_velocity_m_s: float | None,
    target_apogee_ft: float | None,
    target_max_velocity_m_s: float | None,
) -> list[ObjectiveReport]:
    reports: list[ObjectiveReport] = []
    if target_apogee_ft and apogee_ft is not None:
        error = abs(apogee_ft - target_apogee_ft) / target_apogee_ft
        reports.append(
            ObjectiveReport(
                name="apogee_ft",
                target=target_apogee_ft,
                predicted=apogee_ft,
                error_pct=error * 100.0,
                units="ft",
            )
        )
    if target_max_velocity_m_s and max_velocity_m_s is not None:
        error = abs(max_velocity_m_s - target_max_velocity_m_s) / target_max_velocity_m_s
        reports.append(
            ObjectiveReport(
                name="max_velocity_m_s",
                target=target_max_velocity_m_s,
                predicted=max_velocity_m_s,
                error_pct=error * 100.0,
                units="m/s",
            )
        )
    return reports


def _stage_fingerprint(stage: MotorStageDefinition) -> dict[str, object]:
    return {
        "stage_id": stage.stage_id,
        "grain_type": str(stage.grain_geometry.type),
        "grain_params": dict(stage.grain_geometry.params),
        "nozzle": {
            "throat_diameter_m": stage.nozzle.throat_diameter_m,
            "exit_diameter_m": stage.nozzle.exit_diameter_m,
            "throat_length_m": stage.nozzle.throat_length_m,
            "conv_angle_deg": stage.nozzle.conv_angle_deg,
            "div_angle_deg": stage.nozzle.div_angle_deg,
            "efficiency": stage.nozzle.efficiency,
            "erosion_coeff": stage.nozzle.erosion_coeff,
            "slag_coeff": stage.nozzle.slag_coeff,
        },
        "propellant_label": {
            "name": stage.propellant_label.name,
            "family": str(stage.propellant_label.family),
            "source": stage.propellant_label.source,
        },
    }


def simulate_two_stage(
    *,
    stage0: MotorStageDefinition,
    stage1: MotorStageDefinition,
    rkt_path: str,
    out_dir: str,
    constraints: ConstraintSet,
    cd_max: float,
    mach_max: float,
    cd_ramp: bool,
    separation_delay_s: float,
    ignition_delay_s: float,
    target_apogee_ft: float | None,
    target_max_velocity_m_s: float | None,
) -> dict[str, object]:
    rocket_length_in = _rocket_length_in(rkt_path)
    stage0_result = _simulate_stage(
        stage0,
        constraints,
        out_dir,
        f"{stage0.stage_id}-stage0",
        rocket_length_in,
    )
    stage1_result = _simulate_stage(
        stage1,
        constraints,
        out_dir,
        f"{stage1.stage_id}-stage1",
        rocket_length_in,
    )

    apogee = simulate_two_stage_apogee(
        stage0=_build_motor_spec(stage0),
        stage1=_build_motor_spec(stage1),
        rkt_path=rkt_path,
        cd_max=cd_max,
        mach_max=mach_max,
        cd_ramp=cd_ramp,
        total_mass_kg=None,
        separation_delay_s=separation_delay_s,
        ignition_delay_s=ignition_delay_s,
    )

    result = {
        "inputs_hash": _compute_inputs_hash(
            {
                "stage0": _stage_fingerprint(stage0),
                "stage1": _stage_fingerprint(stage1),
                "rkt_path": rkt_path,
                "constraints": {
                    "max_pressure_psi": constraints.max_pressure_psi,
                    "max_kn": constraints.max_kn,
                    "max_mass_flux": constraints.max_mass_flux,
                    "max_vehicle_length_in": constraints.max_vehicle_length_in,
                    "soft_constraints": dict(constraints.soft_constraints),
                },
                "cd_max": cd_max,
                "mach_max": mach_max,
                "cd_ramp": cd_ramp,
                "separation_delay_s": separation_delay_s,
                "ignition_delay_s": ignition_delay_s,
                "target_apogee_ft": target_apogee_ft,
                "target_max_velocity_m_s": target_max_velocity_m_s,
            }
        ),
        "engine_versions": {
            "openmotor_motorlib": openmotor_motorlib_version(),
            "trajectory_engine": trajectory_engine_version(),
        },
        "stage0": {
            "metrics": stage0_result.metrics,
            "violations": stage0_result.violations,
        },
        "stage1": {
            "metrics": stage1_result.metrics,
            "violations": stage1_result.violations,
        },
        "trajectory": {
            "apogee_ft": apogee.apogee_m * 3.28084,
            "apogee_m": apogee.apogee_m,
            "max_velocity_m_s": apogee.max_velocity_m_s,
            "max_accel_m_s2": apogee.max_accel_m_s2,
        },
        "objective_reports": [
            r.__dict__
            for r in _objective_reports(
                apogee.apogee_m * 3.28084,
                apogee.max_velocity_m_s,
                target_apogee_ft,
                target_max_velocity_m_s,
            )
        ],
    }
    if rocket_length_in is not None:
        result["trajectory"]["rocket_length_in"] = rocket_length_in
    return result
