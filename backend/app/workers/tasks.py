import logging
from typing import Any

from app.db.queries import update_job
from app.engine.openmotor.internal_ballistics import run_internal_ballistics
from app.engine.openrocket.runner import run_openrocket_simulation
from app.engine.optimizer.evolutionary import run_evolutionary_optimization
from app.engine.optimizer.input_optimizer import run_input_optimization
from app.workers.celery_app import celery_app

logger = logging.getLogger("arx.backend.worker")


@celery_app.task(bind=True, name="run_simulation")
def run_simulation_task(self, job_id: str, params: dict[str, Any]) -> None:
    update_job(job_id, status="running")
    try:
        openrocket_result = run_openrocket_simulation(params)
        openmotor_result = run_internal_ballistics(params)
        result = {"openrocket": openrocket_result, "openmotor": openmotor_result}
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
