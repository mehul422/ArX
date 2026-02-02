from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import (
    JobResponse,
    MissionTargetSearch,
    MissionTargetWeights,
    OptimizationInputRequest,
    OptimizationRequest,
    V1JobResponse,
    V1ManualTestReport,
    V1MotorFirstRequest,
    V1MissionTargetRequest,
    V1TargetOnlyMissionRequest,
)
from app.api.v1.units import in_to_m, lb_to_kg
from app.api.v1.v1_mappers import build_v1_job_response
from app.api.v1.units import convert_mass_length_payload
from app.db.queries import fetch_job, insert_job
from app.workers.tasks import (
    run_input_optimization_task,
    run_mission_target_task,
    run_motor_first_task,
    run_optimization_task,
)

router = APIRouter(tags=["optimization"])
# v1 mission-target mapping helpers


def _default_design_space() -> MissionTargetSearch:
    return MissionTargetSearch(
        diameter_scales=[0.6, 0.8, 1.0, 1.2, 1.4],
        length_scales=[0.6, 0.8, 1.0, 1.2, 1.4],
        core_scales=[0.7, 0.85, 1.0, 1.15],
        throat_scales=[0.7, 0.85, 1.0, 1.15],
        exit_scales=[0.8, 1.0, 1.2, 1.4],
        grain_count=None,
    )


def _fast_design_space() -> MissionTargetSearch:
    return MissionTargetSearch(
        diameter_scales=[0.8, 1.0, 1.2],
        length_scales=[0.8, 1.0, 1.2],
        core_scales=[0.85, 1.0],
        throat_scales=[0.85, 1.0],
        exit_scales=[1.0, 1.2],
        grain_count=None,
    )


def _default_design_space_fast() -> MissionTargetSearch:
    return MissionTargetSearch(
        diameter_scales=[0.8, 1.0, 1.2],
        length_scales=[0.8, 1.0, 1.2],
        core_scales=[0.85, 1.0],
        throat_scales=[0.85, 1.0],
        exit_scales=[1.0, 1.2],
        grain_count=None,
    )


def _build_mission_target_params(request: V1MissionTargetRequest) -> dict:
    objectives = request.objectives or []
    if not objectives and (request.target_apogee_ft or request.max_velocity_m_s):
        if request.target_apogee_ft:
            objectives.append(
                {"name": "apogee_ft", "target": request.target_apogee_ft, "units": "ft"}
            )
        if request.max_velocity_m_s:
            objectives.append(
                {"name": "max_velocity_m_s", "target": request.max_velocity_m_s, "units": "m/s"}
            )

    target_apogee_ft = None
    max_velocity_m_s = None
    for obj in objectives:
        name = obj["name"] if isinstance(obj, dict) else obj.name
        target = obj["target"] if isinstance(obj, dict) else obj.target
        if name == "apogee_ft":
            target_apogee_ft = target
        if name == "max_velocity_m_s":
            max_velocity_m_s = target

    vehicle = request.vehicle
    base_ric_path = (
        vehicle.stage0_ric_path if vehicle and vehicle.stage0_ric_path else (vehicle.base_ric_path if vehicle else request.base_ric_path)
    )
    stage1_ric_path = (
        vehicle.stage1_ric_path if vehicle and vehicle.stage1_ric_path else None
    )
    rkt_path = vehicle.rkt_path if vehicle else request.rkt_path
    if not base_ric_path or not rkt_path:
        raise ValueError("vehicle.base_ric_path or stage0_ric_path + stage1_ric_path and rkt_path are required")

    solver = request.solver_config
    design_space = solver.design_space if solver and solver.design_space else None
    if design_space:
        search = MissionTargetSearch(
            diameter_scales=design_space.diameter_scales,
            length_scales=design_space.length_scales,
            core_scales=design_space.core_scales,
            throat_scales=design_space.throat_scales,
            exit_scales=design_space.exit_scales,
            grain_count=design_space.grain_count,
        )
    else:
        if request.stage_count == 2:
            search = request.search or _default_design_space_fast()
        else:
            search = request.search or _default_design_space()
    split_ratios = solver.split_ratios if solver and solver.split_ratios else request.split_ratios
    if not split_ratios:
        split_ratios = (
            [0.3, 0.35, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]
            if request.fast_mode
            else [0.5]
        )

    weights = solver.weights if solver and solver.weights else request.weights
    if weights is None:
        weights = MissionTargetWeights()

    allowed_propellants = request.allowed_propellants
    allowed_families = (
        allowed_propellants.families
        if allowed_propellants and allowed_propellants.families
        else request.allowed_propellant_families
    )
    allowed_names = (
        allowed_propellants.names
        if allowed_propellants and allowed_propellants.names
        else request.allowed_propellant_names
    )
    preset_path = (
        allowed_propellants.preset_path
        if allowed_propellants and allowed_propellants.preset_path
        else request.preset_path
    )

    tolerance_pct = (
        solver.tolerance_pct
        if solver and solver.tolerance_pct is not None
        else (request.tolerance_pct or 0.02)
    )

    objectives_payload = [
        obj if isinstance(obj, dict) else obj.model_dump() for obj in objectives
    ]

    total_mass_lb = (
        solver.total_mass_lb
        if solver and solver.total_mass_lb is not None
        else (request.total_mass_lb or (vehicle.total_mass_lb if vehicle else None))
    )
    total_mass_kg = lb_to_kg(total_mass_lb) if total_mass_lb is not None else None

    return {
        "base_ric_path": base_ric_path,
        "stage1_ric_path": stage1_ric_path,
        "rkt_path": rkt_path,
        "output_dir": request.output_dir or "backend/tests",
        "total_target_impulse_ns": request.total_target_impulse_ns,
        "target_apogee_ft": target_apogee_ft,
        "max_velocity_m_s": max_velocity_m_s,
        "tolerance_pct": tolerance_pct,
        "constraints": request.constraints.model_dump(),
        "search": search.model_dump(),
        "split_ratios": split_ratios,
        "cd_max": solver.cd_max if solver and solver.cd_max is not None else (request.cd_max or 0.5),
        "mach_max": solver.mach_max if solver and solver.mach_max is not None else (request.mach_max or 2.0),
        "cd_ramp": solver.cd_ramp if solver and solver.cd_ramp is not None else (request.cd_ramp or False),
        "total_mass_kg": total_mass_kg,
        "separation_delay_s": (
            solver.separation_delay_s
            if solver and solver.separation_delay_s is not None
            else (request.separation_delay_s or 0.0)
        ),
        "ignition_delay_s": (
            solver.ignition_delay_s
            if solver and solver.ignition_delay_s is not None
            else (request.ignition_delay_s or 0.0)
        ),
        "allowed_propellant_families": allowed_families,
        "allowed_propellant_names": allowed_names,
        "preset_path": preset_path,
        "weights": weights.model_dump(),
        "objectives": objectives_payload,
    }


def _build_target_only_params(request: V1TargetOnlyMissionRequest) -> dict:
    objectives = request.objectives or []
    target_apogee_ft = None
    max_velocity_m_s = None
    for obj in objectives:
        name = obj["name"] if isinstance(obj, dict) else obj.name
        target = obj["target"] if isinstance(obj, dict) else obj.target
        if name == "apogee_ft":
            target_apogee_ft = target
        if name == "max_velocity_m_s":
            max_velocity_m_s = target

    solver = request.solver_config
    design_space = solver.design_space if solver and solver.design_space else None
    if design_space:
        search = MissionTargetSearch(
            diameter_scales=design_space.diameter_scales,
            length_scales=design_space.length_scales,
            core_scales=design_space.core_scales,
            throat_scales=design_space.throat_scales,
            exit_scales=design_space.exit_scales,
            grain_count=design_space.grain_count,
        )
    elif request.search:
        search = request.search
    else:
        search = _fast_design_space() if request.fast_mode else _default_design_space()
    split_ratios = solver.split_ratios if solver and solver.split_ratios else request.split_ratios
    if not split_ratios:
        split_ratios = [0.5]

    weights = solver.weights if solver and solver.weights else request.weights
    if weights is None:
        weights = MissionTargetWeights()

    allowed_propellants = request.allowed_propellants
    allowed_families = (
        allowed_propellants.families
        if allowed_propellants and allowed_propellants.families
        else request.allowed_propellant_families
    )
    allowed_names = (
        allowed_propellants.names
        if allowed_propellants and allowed_propellants.names
        else request.allowed_propellant_names
    )
    preset_path = (
        allowed_propellants.preset_path
        if allowed_propellants and allowed_propellants.preset_path
        else request.preset_path
    )
    if request.fast_mode and not allowed_families and not allowed_names:
        allowed_names = ["AP/Al/HTPB", "AP/HTPB", "APCP"]

    tolerance_pct = (
        solver.tolerance_pct
        if solver and solver.tolerance_pct is not None
        else (request.tolerance_pct or 0.02)
    )

    objectives_payload = [
        obj if isinstance(obj, dict) else obj.model_dump() for obj in objectives
    ]

    vehicle = request.vehicle
    vehicle_params = {
        "ref_diameter_m": in_to_m(vehicle.ref_diameter_in),
        "rocket_length_in": vehicle.rocket_length_in,
    }

    return {
        "target_only": True,
        "output_dir": request.output_dir or "backend/tests",
        "total_target_impulse_ns": None,
        "target_apogee_ft": target_apogee_ft,
        "max_velocity_m_s": max_velocity_m_s,
        "tolerance_pct": tolerance_pct,
        "stage_count": request.stage_count,
        "fast_mode": request.fast_mode,
        "velocity_calibration": request.velocity_calibration,
        "constraints": request.constraints.model_dump(),
        "search": search.model_dump(),
        "split_ratios": split_ratios,
        "cd_max": solver.cd_max if solver and solver.cd_max is not None else (request.cd_max or 0.5),
        "mach_max": solver.mach_max if solver and solver.mach_max is not None else (request.mach_max or 2.0),
        "cd_ramp": solver.cd_ramp if solver and solver.cd_ramp is not None else (request.cd_ramp or False),
        "total_mass_kg": (
            lb_to_kg(solver.total_mass_lb)
            if solver and solver.total_mass_lb is not None
            else lb_to_kg(vehicle.total_mass_lb)
        ),
        "separation_delay_s": solver.separation_delay_s if solver and solver.separation_delay_s is not None else (request.separation_delay_s or 0.0),
        "ignition_delay_s": solver.ignition_delay_s if solver and solver.ignition_delay_s is not None else (request.ignition_delay_s or 0.0),
        "allowed_propellant_families": allowed_families,
        "allowed_propellant_names": allowed_names,
        "preset_path": preset_path,
        "weights": weights.model_dump(),
        "objectives": objectives_payload,
        "vehicle_params": vehicle_params,
    }


@router.post("/optimize/mission-target", response_model=V1JobResponse)
def enqueue_mission_target(request: V1MissionTargetRequest):
    params = _build_mission_target_params(request)
    job_id = insert_job(job_type="mission_target", params=params)
    run_mission_target_task.delay(job_id, params)
    return build_v1_job_response(fetch_job(job_id), job_kind="mission_target")


@router.post("/optimize/mission-target/target-only", response_model=V1JobResponse)
def enqueue_mission_target_target_only(request: V1TargetOnlyMissionRequest):
    try:
        params = _build_target_only_params(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    job_id = insert_job(job_type="mission_target", params=params)
    run_mission_target_task.delay(job_id, params)
    return build_v1_job_response(fetch_job(job_id), job_kind="mission_target")


def _build_motor_first_params(request: V1MotorFirstRequest) -> dict:
    objectives_payload = [
        {"name": obj.name, "target": obj.target, "units": obj.units}
        for obj in request.objectives
    ]
    return {
        "objectives": objectives_payload,
        "constraints": request.constraints.model_dump(),
        "motor_ric_path": request.motor_ric_path,
        "motor_spec": request.motor_spec.model_dump() if request.motor_spec else None,
        "design_space": request.design_space.model_dump() if request.design_space else None,
        "output_dir": request.output_dir,
        "cd_max": request.cd_max,
        "mach_max": request.mach_max,
        "cd_ramp": request.cd_ramp,
        "tolerance_pct": request.tolerance_pct,
        "ai_prompt": request.ai_prompt,
    }


@router.post("/optimize/motor-first", response_model=V1JobResponse)
def enqueue_motor_first(request: V1MotorFirstRequest):
    params = _build_motor_first_params(request)
    job_id = insert_job(job_type="motor_first", params=params)
    run_motor_first_task.delay(job_id, params)
    return build_v1_job_response(fetch_job(job_id), job_kind="motor_first")


@router.get("/optimize/motor-first/{job_id}", response_model=V1JobResponse)
def get_motor_first(job_id: str):
    job = fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.get("type") != "motor_first":
        raise HTTPException(status_code=400, detail="job is not motor_first")
    return build_v1_job_response(job, job_kind="motor_first")


@router.get("/optimize/mission-target/{job_id}", response_model=V1JobResponse)
def get_mission_target(job_id: str):
    job = fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.get("type") != "mission_target":
        raise HTTPException(status_code=400, detail="job is not mission_target")
    return build_v1_job_response(job, job_kind="mission_target")


def _build_manual_report(job: dict[str, object]) -> V1ManualTestReport:
    result = job.get("result") or {}
    motorlib = result.get("openmotor_motorlib_result") or {}
    candidates = motorlib.get("candidates") or []
    report_candidates = []
    for candidate in candidates:
        metrics = convert_mass_length_payload(candidate.get("metrics") or {})
        predicted = {
            "apogee_ft": candidate.get("apogee_ft"),
            "max_velocity_m_s": candidate.get("max_velocity_m_s"),
            "max_accel_m_s2": candidate.get("max_accel_m_s2"),
            "metrics": metrics,
            "metrics_units": {
                "peak_chamber_pressure": "Pa",
                "average_chamber_pressure": "Pa",
                "total_impulse": "N*s",
                "average_thrust": "N",
                "burn_time": "s",
                "delivered_specific_impulse": "s",
                "peak_kn": "dimensionless",
                "port_to_throat_ratio": "dimensionless",
                "volume_loading": "fraction",
                "peak_mass_flux": "kg/m^2/s",
                "propellant_mass_lb": "lb",
                "propellant_length_in": "in",
            },
        }
        predicted = convert_mass_length_payload(predicted)
        report_candidates.append(
            {
                "propellant": candidate.get("propellant"),
                "split_ratio": candidate.get("split_ratio"),
                "predicted": predicted,
                "artifacts": candidate.get("artifacts") or {},
                "objective_reports": candidate.get("objective_reports"),
                "manual_openmotor": {
                    "status": "pending",
                    "notes": None,
                    "total_impulse_ns": None,
                    "burn_time_s": None,
                    "peak_pressure_psi": None,
                    "peak_kn": None,
                },
            }
        )
    return V1ManualTestReport(
        job_id=str(job.get("id")),
        inputs_hash=result.get("inputs_hash"),
        engine_versions=result.get("engine_versions") or {},
        objectives=None,
        summary=motorlib.get("summary"),
        candidates=report_candidates,
    )


@router.get("/optimize/mission-target/{job_id}/manual-report", response_model=V1ManualTestReport)
def get_mission_target_manual_report(job_id: str):
    job = fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job.get("type") != "mission_target":
        raise HTTPException(status_code=400, detail="job is not mission_target")
    if job.get("status") != "completed" or not job.get("result"):
        raise HTTPException(status_code=409, detail="job not completed")
    return _build_manual_report(job)


@router.post("/optimize", response_model=JobResponse)
def enqueue_optimization(request: OptimizationRequest):
    job_id = insert_job(job_type="optimize", params=request.params)
    run_optimization_task.delay(job_id, request.params)
    return fetch_job(job_id)


@router.post("/optimize/inputs/{input_id}", response_model=JobResponse)
def enqueue_input_optimization(input_id: str, request: OptimizationInputRequest):
    params = request.model_dump()
    params["input_id"] = input_id
    job_id = insert_job(job_type="optimize_input", params=params)
    run_input_optimization_task.delay(job_id, input_id, params)
    return fetch_job(job_id)


@router.get("/optimize/{job_id}", response_model=JobResponse)
def get_optimization(job_id: str):
    job = fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@router.get("/optimize/{job_id}/summary")
def get_optimization_summary(job_id: str):
    job = fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if job["status"] != "completed" or not job.get("result"):
        return {"id": job["id"], "status": job["status"], "result": None}
    result = job["result"]
    return {
        "id": job["id"],
        "status": job["status"],
        "summary": result.get("summary"),
        "recommended": result.get("recommended"),
    }
