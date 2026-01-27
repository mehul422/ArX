from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import JobResponse, OptimizationInputRequest, OptimizationRequest
from app.db.queries import fetch_job, insert_job
from app.workers.tasks import run_input_optimization_task, run_optimization_task

router = APIRouter(tags=["optimization"])


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
