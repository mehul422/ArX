from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.v1.schemas_openrocket_like_legacy import OpenRocketLikeLegacySimRequestSchema
from app.engine.openrocket_like_legacy.models import (
    ConstraintSet,
    GrainGeometry,
    GrainGeometryType,
    MotorStageDefinition,
    NozzleConfig,
    PropellantLabel,
)
from app.engine.openrocket_like_legacy.sim_pipeline import simulate_two_stage

router = APIRouter(prefix="/simulation-legacy", tags=["simulation-legacy"])


@router.get("/health")
def simulation_legacy_health():
    return {"status": "ok"}


@router.post("/openrocket-like")
def simulate_openrocket_like_legacy(request: OpenRocketLikeLegacySimRequestSchema):
    try:
        stage0 = MotorStageDefinition(
            stage_id=request.stage0.stage_id,
            grain_geometry=GrainGeometry(
                type=GrainGeometryType(request.stage0.grain_geometry.type),
                params=request.stage0.grain_geometry.params,
            ),
            nozzle=NozzleConfig(**request.stage0.nozzle.model_dump()),
            propellant_label=PropellantLabel(
                name=request.stage0.propellant_label.name,
                family=request.stage0.propellant_label.family,
                source=request.stage0.propellant_label.source,
            ),
            propellant_physics=request.stage0.propellant_physics,
        )
        stage1 = MotorStageDefinition(
            stage_id=request.stage1.stage_id,
            grain_geometry=GrainGeometry(
                type=GrainGeometryType(request.stage1.grain_geometry.type),
                params=request.stage1.grain_geometry.params,
            ),
            nozzle=NozzleConfig(**request.stage1.nozzle.model_dump()),
            propellant_label=PropellantLabel(
                name=request.stage1.propellant_label.name,
                family=request.stage1.propellant_label.family,
                source=request.stage1.propellant_label.source,
            ),
            propellant_physics=request.stage1.propellant_physics,
        )
        constraints = ConstraintSet(**request.constraints.model_dump())
        return simulate_two_stage(
            stage0=stage0,
            stage1=stage1,
            rkt_path=request.rkt_path,
            out_dir=request.output_dir,
            constraints=constraints,
            cd_max=request.cd_max,
            mach_max=request.mach_max,
            cd_ramp=request.cd_ramp,
            separation_delay_s=request.separation_delay_s,
            ignition_delay_s=request.ignition_delay_s,
            target_apogee_ft=request.target_apogee_ft,
            target_max_velocity_m_s=request.target_max_velocity_m_s,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
