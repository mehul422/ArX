from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import JobResponse, OptimizationRequest
from app.db.queries import fetch_job, insert_job
from app.workers.tasks import run_optimization_task

router = APIRouter(tags=["optimization"])


@router.post("/optimize", response_model=JobResponse)
def enqueue_optimization(request: OptimizationRequest):
    job_id = insert_job(job_type="optimize", params=request.params)
    run_optimization_task.delay(job_id, request.params)
    return fetch_job(job_id)


@router.get("/optimize/{job_id}", response_model=JobResponse)
def get_optimization(job_id: str):
    job = fetch_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job
