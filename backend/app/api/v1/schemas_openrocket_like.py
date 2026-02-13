from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class PropellantLabelSchema(BaseModel):
    name: str
    family: Literal["commercial", "sugar", "experimental", "unknown"] = "unknown"
    source: Literal["builtin", "imported", "user"] = "user"


class GrainGeometrySchema(BaseModel):
    type: Literal["BATES", "Finocyl", "Moon", "Slot", "Star", "Custom"]
    params: dict[str, float]


class NozzleConfigSchema(BaseModel):
    throat_diameter_m: float = Field(..., gt=0)
    exit_diameter_m: float = Field(..., gt=0)
    throat_length_m: float = Field(default=0.0, ge=0)
    conv_angle_deg: float = Field(default=35.0, gt=0)
    div_angle_deg: float = Field(default=12.0, gt=0)
    efficiency: float = Field(default=1.0, gt=0)
    erosion_coeff: float = Field(default=0.0, ge=0)
    slag_coeff: float = Field(default=0.0, ge=0)


class MotorStageDefinitionSchema(BaseModel):
    stage_id: str
    grain_geometry: GrainGeometrySchema
    nozzle: NozzleConfigSchema
    propellant_label: PropellantLabelSchema
    propellant_physics: dict[str, Any] | None = None


class ConstraintSetSchema(BaseModel):
    max_pressure_psi: float | None = Field(default=None, gt=0)
    max_kn: float | None = Field(default=None, gt=0)
    max_mass_flux: float | None = Field(default=None, gt=0)
    max_vehicle_length_in: float | None = Field(default=None, gt=0)
    soft_constraints: dict[str, float] = Field(default_factory=dict)


class ObjectiveSchema(BaseModel):
    name: str
    target: float
    tolerance_pct: float | None = Field(default=None, gt=0)
    weight: float | None = None


class ObjectiveReportSchema(BaseModel):
    name: str
    target: float
    predicted: float
    error_pct: float
    units: str | None = None


class ArtifactRecordSchema(BaseModel):
    kind: Literal["eng", "ric"]
    path: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MotorRecordSchema(BaseModel):
    designation: str
    diameter_m: float
    length_m: float
    motor_type: str
    manufacturer: str | None = None
    propellant_label: str | None = None
    delays_s: list[float] = Field(default_factory=list)
    thrust_curve: list[tuple[float, float]]
    source: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class MotorImportResponseSchema(BaseModel):
    record: MotorRecordSchema
    warnings: list[str] = Field(default_factory=list)


class SimulationRunSchema(BaseModel):
    inputs_hash: str
    engine_versions: dict[str, Any]
    request: dict[str, Any]


class SimulationResultSchema(BaseModel):
    stage0: dict[str, Any]
    stage1: dict[str, Any]
    trajectory: dict[str, Any]
    objective_reports: list[ObjectiveReportSchema]


class OpenRocketLikeSimRequestSchema(BaseModel):
    stage0: MotorStageDefinitionSchema
    stage1: MotorStageDefinitionSchema
    rkt_path: str
    output_dir: str = "backend/tests"
    constraints: ConstraintSetSchema
    cd_max: float = Field(default=0.5, gt=0)
    mach_max: float = Field(default=2.0, gt=0)
    cd_ramp: bool = False
    separation_delay_s: float = Field(default=0.0, ge=0.0)
    ignition_delay_s: float = Field(default=0.0, ge=0.0)
    target_apogee_ft: float | None = Field(default=None, gt=0)
    target_max_velocity_m_s: float | None = Field(default=None, gt=0)

