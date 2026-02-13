from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class NoseCone(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    type: Literal["OGIVE", "CONICAL", "ELLIPTICAL", "PARABOLIC"]
    length_m: float = Field(..., gt=0)
    diameter_m: float = Field(..., gt=0)
    material: str | None = None


class Bulkhead(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    height_m: float = Field(..., gt=0)
    material: str | None = None
    position_from_top_m: float = Field(default=0.0, ge=0)


class InnerTube(BaseModel):
    type: Literal["inner_tube"] = "inner_tube"
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    outer_diameter_m: float = Field(..., gt=0)
    inner_diameter_m: float | None = Field(default=None, gt=0)
    length_m: float = Field(..., gt=0)
    position_from_bottom_m: float = Field(default=0.0, ge=0)
    is_motor_mount: bool = False


class ParachuteRef(BaseModel):
    type: Literal["parachute"] = "parachute"
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    library_id: str = Field(..., min_length=1)
    diameter_m: float | None = Field(default=None, gt=0)
    position_from_bottom_m: float = Field(default=0.0, ge=0)


class TelemetryMass(BaseModel):
    type: Literal["telemetry"] = "telemetry"
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    mass_kg: float = Field(..., gt=0)
    position_from_bottom_m: float = Field(default=0.0, ge=0)


class BallastMass(BaseModel):
    type: Literal["ballast"] = "ballast"
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    mass_kg: float = Field(..., gt=0)
    position_from_bottom_m: float = Field(default=0.0, ge=0)


Component = InnerTube | ParachuteRef | TelemetryMass | BallastMass
ComponentField = Annotated[Component, Field(discriminator="type")]


class BodyTube(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    length_m: float = Field(..., gt=0)
    diameter_m: float = Field(..., gt=0)
    wall_thickness_m: float | None = Field(default=None, gt=0)
    children: list[ComponentField] = Field(default_factory=list)


class Stage(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    length_m: float = Field(..., gt=0)
    diameter_m: float = Field(..., gt=0)
    motor_mount: InnerTube
    bulkhead: Bulkhead

    @model_validator(mode="after")
    def validate_bulkhead_position(self):
        if self.bulkhead.position_from_top_m != 0.0:
            raise ValueError("bulkhead must be mounted at the top of the stage")
        return self


class FinSet(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    parent_tube_id: str = Field(..., min_length=1)
    fin_count: int = Field(..., ge=1)
    root_chord_m: float = Field(..., gt=0)
    tip_chord_m: float = Field(..., gt=0)
    span_m: float = Field(..., gt=0)
    sweep_m: float = Field(default=0.0, ge=0)
    thickness_m: float = Field(default=0.003, gt=0)
    position_from_bottom_m: float = Field(default=0.0, ge=0)


class RocketAssembly(BaseModel):
    name: str = Field(..., min_length=1)
    design_mode: Literal["MANUAL", "AUTO"]
    global_diameter_m: float = Field(..., gt=0)
    nose_cone: NoseCone
    stages: list[Stage] = Field(default_factory=list)
    body_tubes: list[BodyTube] = Field(default_factory=list)
    fin_sets: list[FinSet] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_structure(self):
        tube_ids = {tube.id for tube in self.body_tubes}
        stage_ids = {stage.id for stage in self.stages}
        all_tube_ids = tube_ids | stage_ids

        if len(tube_ids) != len(self.body_tubes):
            raise ValueError("body tube ids must be unique")
        if len(stage_ids) != len(self.stages):
            raise ValueError("stage ids must be unique")

        for tube in self.body_tubes:
            if abs(tube.diameter_m - self.global_diameter_m) > 1e-9:
                raise ValueError("body tube diameter must match global_diameter_m")

        for stage in self.stages:
            if abs(stage.diameter_m - self.global_diameter_m) > 1e-9:
                raise ValueError("stage diameter must match global_diameter_m")

        if abs(self.nose_cone.diameter_m - self.global_diameter_m) > 1e-9:
            raise ValueError("nose cone diameter must match global_diameter_m")

        for fin in self.fin_sets:
            if fin.parent_tube_id not in all_tube_ids:
                raise ValueError(f"fin parent_tube_id not found: {fin.parent_tube_id}")
        return self


class AutoBuildConstraints(BaseModel):
    upper_length_m: float = Field(..., gt=0)
    upper_mass_kg: float = Field(..., gt=0)
    target_apogee_m: float | None = Field(default=None, gt=0)


class AutoBuildRequest(BaseModel):
    ric_path: str | None = None
    ric_paths: list[str] | None = None
    constraints: AutoBuildConstraints
    include_ballast: bool = False
    include_telemetry: bool = True
    include_parachute: bool = True
    stage_count: int | None = Field(default=None, ge=1, le=5)
    name: str | None = None
    top_n: int = Field(default=5, ge=1, le=20)
    random_seed: int | None = None

    @model_validator(mode="after")
    def validate_ric_inputs(self):
        has_single = bool(self.ric_path and self.ric_path.strip())
        has_multi = bool(self.ric_paths and any(path.strip() for path in self.ric_paths))
        if not has_single and not has_multi:
            raise ValueError("provide ric_path or ric_paths")
        return self


class ModuleRAutoBuildResponse(BaseModel):
    assembly: RocketAssembly
    ork_path: str | None = None
    created_at: datetime
