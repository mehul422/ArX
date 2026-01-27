from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class MaterialSpec(BaseModel):
    name: str
    density_kg_m3: float
    type: Literal["BULK", "SURFACE", "LINE"] = "BULK"


class SimulationRequest(BaseModel):
    rocket_path: str
    motor_source: Literal["bundled", "uploaded"]
    motor_id: str | None = None
    flight_config_id: str | None = None
    use_all_stages: bool = True
    material_mode: Literal["auto", "custom"] = "auto"
    material_default: MaterialSpec | None = None
    material_overrides: dict[str, MaterialSpec] | None = None
    pressure_pa: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_motor_selection(self):
        if not self.motor_id:
            raise ValueError("motor_id is required for bundled or uploaded motors")
        return self


class MetricsSummaryRequest(BaseModel):
    rocket_path: str
    motor_source: Literal["bundled", "uploaded"] | None = None
    motor_id: str | None = None
    motor_mass_kg: float | None = Field(default=None, gt=0)
    motor_length_m: float | None = Field(default=None, gt=0)
    flight_config_id: str | None = None
    use_all_stages: bool = True
    material_mode: Literal["auto", "custom"] = "auto"
    material_default: MaterialSpec | None = None
    material_overrides: dict[str, MaterialSpec] | None = None
    pressure_pa: float | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_motor_selection(self):
        if self.motor_source and not self.motor_id:
            raise ValueError("motor_id is required when motor_source is provided")
        if self.motor_id and not self.motor_source:
            raise ValueError("motor_source is required when motor_id is provided")
        return self


class PipelineRequest(BaseModel):
    rocket_path: str
    motor_source: Literal["bundled", "uploaded"]
    motor_id: str
    motor_mass_kg: float | None = Field(None, gt=0)
    motor_length_m: float | None = Field(None, gt=0)
    flight_config_id: str | None = None
    use_all_stages: bool = True
    material_mode: Literal["auto", "custom"] = "auto"
    material_default: MaterialSpec | None = None
    material_overrides: dict[str, MaterialSpec] | None = None
    pressure_pa: float | None = None
    include_geometry: bool = False
    apply_materials: bool | None = None


class OptimizationRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class OptimizationInputRequest(BaseModel):
    iterations: int = Field(default=25, gt=0)
    population_size: int = Field(default=30, gt=0)


class InputConstraints(BaseModel):
    max_total_mass_kg: float | None = None

    @model_validator(mode="after")
    def validate_constraints(self):
        if self.max_total_mass_kg is not None and self.max_total_mass_kg <= 0:
            raise ValueError("max_total_mass_kg must be positive")
        return self


class UserInputRequest(BaseModel):
    target_apogee_m: float = Field(..., gt=0)
    altitude_margin_m: float = Field(default=0.0, ge=0.0)
    max_mach: float | None = Field(default=None, gt=0)
    max_diameter_m: float | None = Field(default=None, gt=0)
    payload_mass_kg: float | None = Field(default=None, gt=0)
    target_thrust_n: float | None = Field(default=None, gt=0)
    constraints: InputConstraints = Field(default_factory=InputConstraints)
    preferences: dict[str, Any] = Field(default_factory=dict)


class UserInputResponse(BaseModel):
    id: str
    target_apogee_m: float
    altitude_margin_m: float
    max_mach: float | None = None
    max_diameter_m: float | None = None
    payload_mass_kg: float | None = None
    target_thrust_n: float | None = None
    constraints: InputConstraints
    preferences: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class MotorInfo(BaseModel):
    motor_id: str
    filename: str
    source: Literal["bundled", "uploaded"]


class MotorUploadResponse(BaseModel):
    motor_id: str
    filename: str
    source: Literal["uploaded"]


class JobResponse(BaseModel):
    id: str
    type: Literal["simulate", "optimize", "optimize_input"]
    status: Literal["queued", "running", "completed", "failed"]
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime
