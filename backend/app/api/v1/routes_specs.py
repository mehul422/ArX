from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import V1VehicleStageSpecRequest, V1VehicleStageSpecResponse
from app.db.queries import (
    fetch_latest_vehicle_spec,
    fetch_vehicle_spec,
    insert_vehicle_spec,
)

router = APIRouter(tags=["specs"])


@router.post("/specs/vehicle", response_model=V1VehicleStageSpecResponse)
def create_vehicle_stage_spec(request: V1VehicleStageSpecRequest):
    payload = request.model_dump()
    spec_id = insert_vehicle_spec(payload)
    record = fetch_vehicle_spec(spec_id)
    if not record:
        raise HTTPException(status_code=500, detail="failed to persist spec")
    stored = record["payload"]
    return V1VehicleStageSpecResponse(
        id=record["id"],
        source_module=stored["source_module"],
        vehicle=stored["vehicle"],
        stage_count=stored["stage_count"],
        separation_delay_s=stored["separation_delay_s"],
        ignition_delay_s=stored["ignition_delay_s"],
        ork_path=stored.get("ork_path"),
        rkt_path=stored.get("rkt_path"),
        created_at=record["created_at"],
    )


@router.get("/specs/vehicle/{spec_id}", response_model=V1VehicleStageSpecResponse)
def get_vehicle_stage_spec(spec_id: str):
    record = fetch_vehicle_spec(spec_id)
    if not record:
        raise HTTPException(status_code=404, detail="spec not found")
    stored = record["payload"]
    return V1VehicleStageSpecResponse(
        id=record["id"],
        source_module=stored["source_module"],
        vehicle=stored["vehicle"],
        stage_count=stored["stage_count"],
        separation_delay_s=stored["separation_delay_s"],
        ignition_delay_s=stored["ignition_delay_s"],
        ork_path=stored.get("ork_path"),
        rkt_path=stored.get("rkt_path"),
        created_at=record["created_at"],
    )


@router.get("/specs/vehicle/latest", response_model=V1VehicleStageSpecResponse)
def get_latest_vehicle_stage_spec():
    record = fetch_latest_vehicle_spec()
    if not record:
        raise HTTPException(status_code=404, detail="spec not found")
    stored = record["payload"]
    return V1VehicleStageSpecResponse(
        id=record["id"],
        source_module=stored["source_module"],
        vehicle=stored["vehicle"],
        stage_count=stored["stage_count"],
        separation_delay_s=stored["separation_delay_s"],
        ignition_delay_s=stored["ignition_delay_s"],
        ork_path=stored.get("ork_path"),
        rkt_path=stored.get("rkt_path"),
        created_at=record["created_at"],
    )
