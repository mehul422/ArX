from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ComponentCategory = Literal[
    "motor_mount",
    "body_tube",
    "inner_tube",
    "ballast",
    "telemetry_module",
    "nose_cone",
    "fin_set",
    "unknown",
]


class MaterialSpec(BaseModel):
    name: str
    density_kg_m3: float = Field(..., gt=0)
    elastic_modulus_pa: float | None = Field(default=None, gt=0)


class LibraryComponent(BaseModel):
    id: str
    vendor: str = "generic"
    name: str
    category: ComponentCategory
    shape: str | None = None
    material: str
    hollow: bool = False
    outer_diameter_m: float | None = Field(default=None, gt=0)
    inner_diameter_m: float | None = Field(default=None, gt=0)
    length_m: float | None = Field(default=None, gt=0)
    wall_thickness_m: float | None = Field(default=None, gt=0)
    mass_kg: float | None = Field(default=None, gt=0)
    span_m: float | None = Field(default=None, gt=0)
    root_chord_m: float | None = Field(default=None, gt=0)
    tip_chord_m: float | None = Field(default=None, gt=0)
    sweep_m: float | None = Field(default=None, ge=0)
    metadata: dict[str, object] = Field(default_factory=dict)


class MotorSpec(BaseModel):
    diameter_m: float = Field(..., gt=0)
    length_m: float = Field(..., gt=0)


class CandidateMassItem(BaseModel):
    id: str
    name: str
    mass_kg: float = Field(..., gt=0)
    position_from_bottom_m: float = Field(default=0.0, ge=0)
    item_type: Literal["telemetry", "ballast"] = "telemetry"


class CandidateInnerTube(BaseModel):
    id: str
    name: str
    outer_diameter_m: float = Field(..., gt=0)
    inner_diameter_m: float = Field(..., gt=0)
    length_m: float = Field(..., gt=0)
    position_from_bottom_m: float = Field(default=0.0, ge=0)
    is_motor_mount: bool = False


class CandidateBodyTube(BaseModel):
    id: str
    name: str
    length_m: float = Field(..., gt=0)
    diameter_m: float = Field(..., gt=0)
    wall_thickness_m: float = Field(..., gt=0)
    material: str
    inner_tubes: list[CandidateInnerTube] = Field(default_factory=list)
    masses: list[CandidateMassItem] = Field(default_factory=list)
    parachute_diameter_m: float | None = Field(default=None, gt=0)
    parachute_position_m: float | None = Field(default=None, ge=0)


class CandidateStage(BaseModel):
    id: str
    name: str
    length_m: float = Field(..., gt=0)
    diameter_m: float = Field(..., gt=0)
    motor_mount: CandidateInnerTube
    bulkhead_height_m: float = Field(..., gt=0)
    bulkhead_material: str = "Phenolic"


class CandidateNoseCone(BaseModel):
    id: str
    name: str
    nose_type: Literal["OGIVE", "CONICAL", "ELLIPTICAL", "PARABOLIC"] = "OGIVE"
    length_m: float = Field(..., gt=0)
    diameter_m: float = Field(..., gt=0)
    material: str


class CandidateFinSet(BaseModel):
    id: str
    name: str
    parent_tube_id: str
    fin_count: int = Field(..., ge=2)
    root_chord_m: float = Field(..., gt=0)
    tip_chord_m: float = Field(..., gt=0)
    span_m: float = Field(..., gt=0)
    sweep_m: float = Field(default=0.0, ge=0)
    thickness_m: float = Field(default=0.003, gt=0)
    position_from_bottom_m: float = Field(default=0.0, ge=0)


class CandidateRocket(BaseModel):
    id: str
    name: str
    global_diameter_m: float = Field(..., gt=0)
    nose_cone: CandidateNoseCone
    stages: list[CandidateStage] = Field(default_factory=list)
    body_tubes: list[CandidateBodyTube] = Field(default_factory=list)
    fin_set: CandidateFinSet
    predicted_apogee_m: float = Field(default=0.0, ge=0)
    total_mass_kg: float = Field(default=0.0, ge=0)
    stability_margin_cal: float = Field(default=0.0)
    score: float = Field(default=0.0, ge=0)
    metadata: dict[str, float | str | int] = Field(default_factory=dict)
