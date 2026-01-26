from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import JobResponse, SimulationRequest
from app.db.queries import fetch_job, insert_job
from app.workers.tasks import run_simulation_task

router = APIRouter(tags=["simulation"])


@router.post("/simulate", response_model=JobResponse)
def enqueue_simulation(request: SimulationRequest):
    job_id = insert_job(job_type="simulate", params=request.params)
    run_simulation_task.delay(job_id, request.params)
    return fetch_job(job_id)


@router.get("/simulate/{job_id}", response_model=JobResponse)
def get_simulation(job_id: str):
    job = fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job
