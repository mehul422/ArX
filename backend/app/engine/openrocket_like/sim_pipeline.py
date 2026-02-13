from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

from app.engine.openmotor_ai.ballistics import TimeStep, aggregate_metrics
from app.engine.openmotor_ai.motorlib_adapter import simulate_motorlib_with_result, metrics_from_simresult
from app.engine.openmotor_ai.propellant_library import load_preset_propellants
from app.engine.openmotor_ai.propellant_schema import PropellantSchema, propellant_to_spec
from app.engine.openmotor_ai.spec import BATESGrain, MotorConfig, MotorSpec, NozzleSpec, PropellantSpec
from app.engine.openrocket_like.constraints import evaluate_constraints
from app.engine.openrocket_like.grains import validate_grain_geometry
from app.engine.openrocket_like.models import (
    ArtifactRecord,
    ConstraintSet,
    GrainGeometryType,
    MotorStageDefinition,
    ObjectiveReport,
)
from app.engine.openrocket_like.nozzle import validate_nozzle
from app.engine.openrocket_like.artifacts import write_motor_artifacts
from app.engine.openmotor_ai.trajectory import simulate_two_stage_apogee
from app.engine.openmotor_ai.engine_versions import openmotor_motorlib_version, trajectory_engine_version
from app.engine.openmotor_ai.ork_reader import read_rocket_dimensions
from app.engine.openmotor_ai.cdx1_reader import read_cdx1_dimensions


@dataclass(frozen=True)
class StageSimulationResult:
    metrics: dict[str, float]
    steps: list[TimeStep]
    artifacts: list[ArtifactRecord]
    violations: list[str]
    engine: str


def _compute_inputs_hash(payload: dict[str, object]) -> str:
    normalized = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _json_safe(value):
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if hasattr(value, "__dict__"):
        return _json_safe(value.__dict__)
    if hasattr(value, "value"):
        return value.value
    return value


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


def simulate_stage(
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
    artifacts = write_motor_artifacts(
        spec=spec,
        steps=steps,
        out_dir=out_dir,
        prefix=artifact_prefix,
        propellant_label=stage.propellant_label.name,
    )
    return StageSimulationResult(
        metrics=metrics | {"simulation_engine": engine},
        steps=steps,
        artifacts=artifacts,
        violations=violations,
        engine=engine,
    )


def objective_reports(
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
    stage0_result = simulate_stage(
        stage0,
        constraints,
        out_dir,
        f"{stage0.stage_id}-stage0",
        rocket_length_in,
    )
    stage1_result = simulate_stage(
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
                "stage0": stage0.__dict__,
                "stage1": stage1.__dict__,
                "rkt_path": rkt_path,
                "constraints": constraints.__dict__,
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
            "artifacts": [a.__dict__ for a in stage0_result.artifacts],
            "violations": stage0_result.violations,
        },
        "stage1": {
            "metrics": stage1_result.metrics,
            "artifacts": [a.__dict__ for a in stage1_result.artifacts],
            "violations": stage1_result.violations,
        },
        "trajectory": {
            "apogee_ft": apogee.apogee_m * 3.28084,
            "apogee_m": apogee.apogee_m,
            "max_velocity_m_s": apogee.max_velocity_m_s,
            "max_accel_m_s2": apogee.max_accel_m_s2,
        },
        "objective_reports": [r.__dict__ for r in objective_reports(
            apogee.apogee_m * 3.28084,
            apogee.max_velocity_m_s,
            target_apogee_ft,
            target_max_velocity_m_s,
        )],
    }
    if rocket_length_in is not None:
        result["trajectory"]["rocket_length_in"] = rocket_length_in
    return result

