import os

from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import JobResponse, MetricsSummaryRequest, PipelineRequest, SimulationRequest
from app.db.queries import fetch_job, insert_job
from app.engine.openrocket.runner import run_openrocket_pipeline, run_openrocket_simulation
from app.motors.storage import resolve_motor_path
from app.workers.tasks import run_simulation_task

router = APIRouter(tags=["simulation"])


def _build_simulation_params(request: SimulationRequest) -> dict:
    if not os.path.isabs(request.rocket_path):
        raise HTTPException(status_code=400, detail="rocket_path must be absolute")
    if not os.path.exists(request.rocket_path):
        raise HTTPException(status_code=404, detail="rocket file not found")
    try:
        motor_path = resolve_motor_path(request.motor_source, request.motor_id or "")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="motor file not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    params = dict(request.params)
    params["rocket_path"] = request.rocket_path
    params["motor_path"] = motor_path
    params["motor_source"] = request.motor_source
    params["motor_id"] = request.motor_id
    params["material_mode"] = request.material_mode
    params["material_default"] = (
        request.material_default.model_dump() if request.material_default else None
    )
    params["material_overrides"] = (
        {key: value.model_dump() for key, value in request.material_overrides.items()}
        if request.material_overrides
        else None
    )
    params["pressure_pa"] = request.pressure_pa
    params["flight_config_id"] = request.flight_config_id
    params["use_all_stages"] = request.use_all_stages
    return params


def _build_metrics_params(request: MetricsSummaryRequest) -> dict:
    if not os.path.isabs(request.rocket_path):
        raise HTTPException(status_code=400, detail="rocket_path must be absolute")
    if not os.path.exists(request.rocket_path):
        raise HTTPException(status_code=404, detail="rocket file not found")

    motor_path = None
    if request.motor_source and request.motor_id:
        try:
            motor_path = resolve_motor_path(request.motor_source, request.motor_id)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="motor file not found")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    params = dict(request.params)
    params["rocket_path"] = request.rocket_path
    params["motor_path"] = motor_path
    params["motor_source"] = request.motor_source
    params["motor_id"] = request.motor_id
    params["motor_mass_kg"] = request.motor_mass_kg
    params["motor_length_m"] = request.motor_length_m
    params["material_mode"] = request.material_mode
    params["material_default"] = (
        request.material_default.model_dump() if request.material_default else None
    )
    params["material_overrides"] = (
        {key: value.model_dump() for key, value in request.material_overrides.items()}
        if request.material_overrides
        else None
    )
    params["pressure_pa"] = request.pressure_pa
    params["flight_config_id"] = request.flight_config_id
    params["use_all_stages"] = request.use_all_stages
    params["allow_missing_motor"] = motor_path is None
    return params


def _build_pipeline_params(request: PipelineRequest) -> dict:
    if not os.path.isabs(request.rocket_path):
        raise HTTPException(status_code=400, detail="rocket_path must be absolute")
    if not os.path.exists(request.rocket_path):
        raise HTTPException(status_code=404, detail="rocket file not found")
    try:
        motor_path = resolve_motor_path(request.motor_source, request.motor_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="motor file not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "rocket_path": request.rocket_path,
        "motor_path": motor_path,
        "motor_source": request.motor_source,
        "motor_id": request.motor_id,
        "motor_mass_kg": request.motor_mass_kg,
        "motor_length_m": request.motor_length_m,
        "material_mode": request.material_mode,
        "material_default": (
            request.material_default.model_dump() if request.material_default else None
        ),
        "material_overrides": (
            {key: value.model_dump() for key, value in request.material_overrides.items()}
            if request.material_overrides
            else None
        ),
        "pressure_pa": request.pressure_pa,
        "flight_config_id": request.flight_config_id,
        "use_all_stages": request.use_all_stages,
        "include_geometry": request.include_geometry,
        "apply_materials": request.apply_materials,
    }


@router.post("/simulate", response_model=JobResponse)
def enqueue_simulation(request: SimulationRequest):
    params = _build_simulation_params(request)

    job_id = insert_job(job_type="simulate", params=params)
    run_simulation_task.delay(job_id, params)
    return fetch_job(job_id)


@router.post("/simulate/metrics")
def simulate_metrics(request: SimulationRequest):
    params = _build_simulation_params(request)
    try:
        return run_openrocket_simulation(params)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/simulate/metrics/summary")
def simulate_metrics_summary(request: MetricsSummaryRequest):
    params = _build_metrics_params(request)
    try:
        result = run_openrocket_simulation(params)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        "cg_in": result.get("cg_in"),
        "cp_in": result.get("cp_in"),
        "total_mass_lb": result.get("total_mass_lb"),
        "stage_masses_lb": result.get("stage_masses_lb"),
        "stability_margin": result.get("stability_margin"),
        "motors_included": result.get("motors_included", False),
    }


@router.post("/simulate/pipeline")
def simulate_pipeline(request: PipelineRequest):
    params = _build_pipeline_params(request)
    try:
        return run_openrocket_pipeline(params)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

@router.get("/simulate/{job_id}", response_model=JobResponse)
def get_simulation(job_id: str):
    job = fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job
