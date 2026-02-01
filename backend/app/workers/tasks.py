import logging
from typing import Any

from app.api.v1.v1_mappers import compute_inputs_hash
from app.db.queries import update_job
from app.engine.openmotor.internal_ballistics import run_internal_ballistics
from app.engine.openmotor_ai.engine_versions import openmotor_motorlib_version, trajectory_engine_version
from app.engine.openrocket.runner import run_openrocket_simulation
from app.engine.optimizer.evolutionary import run_evolutionary_optimization
from app.engine.optimizer.input_optimizer import run_input_optimization
from app.workers.celery_app import celery_app

logger = logging.getLogger("arx.backend.worker")


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


@celery_app.task(bind=True, name="run_simulation")
def run_simulation_task(self, job_id: str, params: dict[str, Any]) -> None:
    update_job(job_id, status="running")
    try:
        openrocket_result = run_openrocket_simulation(params)
        openmotor_result = run_internal_ballistics(params)
        result = {
            "openrocket": openrocket_result,
            "internal_ballistics_estimate": openmotor_result,
            "deprecated_aliases": {"openmotor": openmotor_result},
            "inputs_hash": compute_inputs_hash(params),
            "engine_versions": {"internal_ballistics": {"id": "internal_v1"}},
        }
        update_job(job_id, status="completed", result=result)
    except Exception as exc:
        logger.exception("simulation failed: %s", exc)
        update_job(job_id, status="failed", error=str(exc))
        raise


@celery_app.task(bind=True, name="run_optimization")
def run_optimization_task(self, job_id: str, params: dict[str, Any]) -> None:
    update_job(job_id, status="running")
    try:
        result = run_evolutionary_optimization(params)
        update_job(job_id, status="completed", result=result)
    except Exception as exc:
        logger.exception("optimization failed: %s", exc)
        update_job(job_id, status="failed", error=str(exc))
        raise


@celery_app.task(bind=True, name="run_input_optimization")
def run_input_optimization_task(
    self, job_id: str, input_id: str, params: dict[str, Any]
) -> None:
    update_job(job_id, status="running")
    try:
        from app.db.queries import fetch_user_input

        record = fetch_user_input(input_id)
        if not record:
            raise RuntimeError("input not found")
        payload = record["payload"]
        iterations = int(params.get("iterations", 25))
        population_size = int(params.get("population_size", 30))
        result = run_input_optimization(payload, iterations=iterations, population_size=population_size)
        update_job(job_id, status="completed", result=result)
    except Exception as exc:
        logger.exception("input optimization failed: %s", exc)
        update_job(job_id, status="failed", error=str(exc))
        raise


@celery_app.task(bind=True, name="run_mission_target")
def run_mission_target_task(self, job_id: str, params: dict[str, Any]) -> None:
    update_job(job_id, status="running")
    try:
        from app.engine.openmotor_ai.openmotor_pipeline import (
            StageSearchConfig,
            TrajectoryTargets,
            TwoStageConstraints,
            mission_targeted_design,
            mission_targeted_design_target_only,
            VehicleParams,
        )
        from app.engine.openmotor_ai.scoring import ScoreWeights

        constraints = TwoStageConstraints(**params["constraints"])
        search = StageSearchConfig(**params["search"])
        targets = TrajectoryTargets(
            apogee_ft=params.get("target_apogee_ft"),
            max_velocity_m_s=params.get("max_velocity_m_s"),
            tolerance_pct=params.get("tolerance_pct", 0.02),
        )
        weights = ScoreWeights(**params["weights"]) if params.get("weights") else None

        if params.get("target_only"):
            vehicle_params = params.get("vehicle_params") or {}
            total_mass_kg = params.get("total_mass_kg") or vehicle_params.get("total_mass_kg")
            ref_diameter_m = vehicle_params.get("ref_diameter_m")
            rocket_length_in = vehicle_params.get("rocket_length_in")
            if ref_diameter_m is None or rocket_length_in is None:
                raise ValueError("ref_diameter_m and rocket_length_in are required for target_only runs")
            if total_mass_kg is None:
                raise ValueError("total_mass_kg is required for target_only runs")
            result = mission_targeted_design_target_only(
                output_dir=params.get("output_dir", "backend/tests"),
                targets=targets,
                constraints=constraints,
                search=search,
                split_ratios=params["split_ratios"],
                cd_max=params.get("cd_max", 0.5),
                mach_max=params.get("mach_max", 2.0),
                cd_ramp=params.get("cd_ramp", False),
                total_mass_kg=total_mass_kg,
                total_target_impulse_ns=params.get("total_target_impulse_ns"),
                separation_delay_s=params.get("separation_delay_s", 0.0),
                ignition_delay_s=params.get("ignition_delay_s", 0.0),
                stage_count=params.get("stage_count", 1),
                velocity_calibration=params.get("velocity_calibration", 1.0),
                fast_mode=params.get("fast_mode", False),
                allowed_propellant_families=params.get("allowed_propellant_families"),
                allowed_propellant_names=params.get("allowed_propellant_names"),
                preset_path=params.get("preset_path"),
                weights=weights,
                vehicle_params=VehicleParams(
                    ref_diameter_m=ref_diameter_m,
                    rocket_length_in=rocket_length_in,
                ),
            )
        else:
            result = mission_targeted_design(
                base_ric_path=params["base_ric_path"],
                stage1_ric_path=params.get("stage1_ric_path"),
                output_dir=params.get("output_dir", "backend/tests"),
                rkt_path=params["rkt_path"],
                total_target_impulse_ns=params.get("total_target_impulse_ns"),
                targets=targets,
                constraints=constraints,
                search=search,
                split_ratios=params["split_ratios"],
                cd_max=params.get("cd_max", 0.5),
                mach_max=params.get("mach_max", 2.0),
                cd_ramp=params.get("cd_ramp", False),
                total_mass_kg=params.get("total_mass_kg"),
                separation_delay_s=params.get("separation_delay_s", 0.0),
                ignition_delay_s=params.get("ignition_delay_s", 0.0),
                allowed_propellant_families=params.get("allowed_propellant_families"),
                allowed_propellant_names=params.get("allowed_propellant_names"),
                preset_path=params.get("preset_path"),
                weights=weights,
                vehicle_params=None,
            )
        engine_versions = {
            "openmotor_motorlib": openmotor_motorlib_version(),
            "trajectory_engine": trajectory_engine_version(),
        }
        result_payload = _json_safe(
            {
                "openmotor_motorlib_result": result,
                "inputs_hash": compute_inputs_hash(params),
                "engine_versions": engine_versions,
            }
        )
        update_job(
            job_id,
            status="completed",
            result=result_payload,
        )
    except Exception as exc:
        logger.exception("mission target failed: %s", exc)
        update_job(job_id, status="failed", error=str(exc))
        raise
