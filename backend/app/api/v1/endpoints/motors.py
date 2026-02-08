from fastapi import APIRouter, HTTPException

from app.services.motor_classifier import (
    calculate_motor_requirements,
    ClassificationRequest,
    SimplifiedMotorSolution,
)

router = APIRouter()


@router.post("/classify", response_model=SimplifiedMotorSolution)
def classify_motor(request: ClassificationRequest):
    try:
        return calculate_motor_requirements(request)
    except (ValueError, Exception) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
