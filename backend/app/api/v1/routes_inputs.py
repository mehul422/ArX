from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import UserInputRequest, UserInputResponse
from app.db.queries import fetch_user_input, insert_user_input

router = APIRouter(tags=["inputs"])


@router.post("/inputs", response_model=UserInputResponse)
def create_user_input(request: UserInputRequest):
    payload = request.model_dump()
    input_id = insert_user_input(payload)
    record = fetch_user_input(input_id)
    if not record:
        raise HTTPException(status_code=500, detail="failed to persist input")
    return UserInputResponse(
        id=record["id"],
        target_apogee_m=payload["target_apogee_m"],
        altitude_margin_m=payload.get("altitude_margin_m", 0.0),
        max_mach=payload.get("max_mach"),
        max_diameter_m=payload.get("max_diameter_m"),
        payload_mass_kg=payload.get("payload_mass_kg"),
        target_thrust_n=payload.get("target_thrust_n"),
        constraints=request.constraints,
        preferences=payload.get("preferences", {}),
        created_at=record["created_at"],
    )


@router.get("/inputs/{input_id}", response_model=UserInputResponse)
def get_user_input(input_id: str):
    record = fetch_user_input(input_id)
    if not record:
        raise HTTPException(status_code=404, detail="input not found")
    payload = record["payload"]
    return UserInputResponse(
        id=record["id"],
        target_apogee_m=payload["target_apogee_m"],
        altitude_margin_m=payload.get("altitude_margin_m", 0.0),
        max_mach=payload.get("max_mach"),
        max_diameter_m=payload.get("max_diameter_m"),
        payload_mass_kg=payload.get("payload_mass_kg"),
        target_thrust_n=payload.get("target_thrust_n"),
        constraints=payload.get("constraints", {}),
        preferences=payload.get("preferences", {}),
        created_at=record["created_at"],
    )
