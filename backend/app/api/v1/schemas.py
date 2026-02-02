from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class MaterialSpec(BaseModel):
    name: str
    density_kg_m3: float
    type: Literal["BULK", "SURFACE", "LINE"] = "BULK"


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


class MissionTargetConstraints(BaseModel):
    max_pressure_psi: float = Field(..., gt=0)
    max_kn: float = Field(..., gt=0)
    max_vehicle_length_in: float = Field(..., gt=0)
    max_stage_length_ratio: float = Field(default=1.15, gt=0)


class MissionTargetSearch(BaseModel):
    diameter_scales: list[float]
    length_scales: list[float]
    core_scales: list[float]
    throat_scales: list[float]
    exit_scales: list[float]
    grain_count: int | None = None


class MissionTargetWeights(BaseModel):
    apogee: float = 0.30
    efficiency: float = 0.20
    thrust_quality: float = 0.15
    pressure_margin: float = 0.10
    kn_margin: float = 0.10
    packaging: float = 0.10
    manufacturability: float = 0.05


class MissionTargetRequest(BaseModel):
    base_ric_path: str
    rkt_path: str
    output_dir: str = "backend/tests"
    total_target_impulse_ns: float | None = Field(default=None, gt=0)
    target_apogee_ft: float | None = Field(default=None, gt=0)
    max_velocity_m_s: float | None = Field(default=None, gt=0)
    tolerance_pct: float = Field(default=0.02, gt=0)
    constraints: MissionTargetConstraints
    search: MissionTargetSearch
    split_ratios: list[float]
    cd_max: float = Field(default=0.5, gt=0)
    mach_max: float = Field(default=2.0, gt=0)
    cd_ramp: bool = False
    total_mass_kg: float | None = Field(default=None, gt=0)
    separation_delay_s: float = Field(default=0.0, ge=0.0)
    ignition_delay_s: float = Field(default=0.0, ge=0.0)
    allowed_propellant_families: list[str] | None = None
    allowed_propellant_names: list[str] | None = None
    preset_path: str | None = None
    weights: MissionTargetWeights | None = None

    @model_validator(mode="after")
    def validate_targets(self):
        if self.target_apogee_ft is None and self.max_velocity_m_s is None:
            raise ValueError("Provide target_apogee_ft and/or max_velocity_m_s")
        return self



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
    type: Literal["simulate", "optimize", "optimize_input", "mission_target"]
    status: Literal["queued", "running", "completed", "failed"]
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class V1Error(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class V1JobResponse(BaseModel):
    api_version: Literal["v1"] = "v1"
    job_kind: Literal["simulate", "mission_target"]
    id: str
    status: Literal["queued", "running", "completed", "failed"]
    params: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: V1Error | None = None
    created_at: datetime
    updated_at: datetime
    type: Literal["simulate", "mission_target"] | None = Field(
        default=None, description="Deprecated alias for job_kind"
    )


class V1Objective(BaseModel):
    name: Literal["apogee_ft", "max_velocity_m_s"]
    target: float = Field(..., gt=0)
    units: str
    tolerance_pct: float | None = Field(default=None, gt=0)
    weight: float | None = Field(default=None, ge=0)


class V1ObjectiveReport(BaseModel):
    name: Literal["apogee_ft", "max_velocity_m_s"]
    target: float
    predicted: float
    error_pct: float
    units: str


class V1ConstraintSet(BaseModel):
    max_pressure_psi: float = Field(..., gt=0, description="psi")
    max_kn: float = Field(..., gt=0, description="dimensionless")
    max_vehicle_length_in: float = Field(..., gt=0, description="in")
    max_stage_length_ratio: float = Field(default=1.15, gt=0, description="dimensionless")


class V1DesignSpace(BaseModel):
    diameter_scales: list[float] = Field(..., description="scale factor")
    length_scales: list[float] = Field(..., description="scale factor")
    core_scales: list[float] = Field(..., description="scale factor")
    throat_scales: list[float] = Field(..., description="scale factor")
    exit_scales: list[float] = Field(..., description="scale factor")
    grain_count: int | None = Field(default=None, gt=0)


class V1SolverConfig(BaseModel):
    split_ratios: list[float] | None = None
    design_space: V1DesignSpace | None = None
    cd_max: float | None = Field(default=None, gt=0, description="dimensionless")
    mach_max: float | None = Field(default=None, gt=0, description="dimensionless")
    cd_ramp: bool | None = None
    total_mass_lb: float | None = Field(default=None, gt=0, description="lb")
    separation_delay_s: float | None = Field(default=None, ge=0, description="s")
    ignition_delay_s: float | None = Field(default=None, ge=0, description="s")
    weights: MissionTargetWeights | None = None
    tolerance_pct: float | None = Field(default=None, gt=0)


class V1AllowedPropellants(BaseModel):
    families: list[str] | None = None
    names: list[str] | None = None
    preset_path: str | None = None


class V1Vehicle(BaseModel):
    base_ric_path: str | None = Field(default=None, description="absolute path to .ric template")
    stage0_ric_path: str | None = Field(default=None, description="absolute path to stage0 .ric")
    stage1_ric_path: str | None = Field(default=None, description="absolute path to stage1 .ric")
    rkt_path: str = Field(..., description="absolute path to .rkt rocket file")
    total_mass_lb: float | None = Field(default=None, gt=0, description="lb")


class V1TargetOnlyVehicle(BaseModel):
    ref_diameter_in: float = Field(..., gt=0, description="in")
    rocket_length_in: float = Field(..., gt=0, description="in")
    total_mass_lb: float = Field(..., gt=0, description="lb")


class V1MissionTargetRequest(BaseModel):
    mode: Literal["guided", "free_form"] = "guided"
    objectives: list[V1Objective] | None = None
    constraints: V1ConstraintSet
    allowed_propellants: V1AllowedPropellants | None = None
    vehicle: V1Vehicle | None = None
    solver_config: V1SolverConfig | None = None

    # Legacy fields (deprecated)
    base_ric_path: str | None = None
    rkt_path: str | None = None
    output_dir: str | None = None
    total_target_impulse_ns: float | None = Field(default=None, gt=0, description="N*s")
    target_apogee_ft: float | None = Field(default=None, gt=0, description="ft")
    max_velocity_m_s: float | None = Field(default=None, gt=0, description="m/s")
    tolerance_pct: float | None = Field(default=None, gt=0)
    split_ratios: list[float] | None = None
    cd_max: float | None = Field(default=None, gt=0)
    mach_max: float | None = Field(default=None, gt=0)
    cd_ramp: bool | None = None
    total_mass_lb: float | None = Field(default=None, gt=0)
    separation_delay_s: float | None = Field(default=None, ge=0)
    ignition_delay_s: float | None = Field(default=None, ge=0)
    allowed_propellant_families: list[str] | None = None
    allowed_propellant_names: list[str] | None = None
    preset_path: str | None = None
    weights: MissionTargetWeights | None = None
    search: MissionTargetSearch | None = None

    @model_validator(mode="after")
    def validate_objectives(self):
        if self.objectives:
            return self
        if self.target_apogee_ft is None and self.max_velocity_m_s is None:
            raise ValueError("Provide at least one objective")
        return self

    @model_validator(mode="after")
    def validate_vehicle_templates(self):
        if self.vehicle:
            if (
                self.vehicle.base_ric_path is None
                and (self.vehicle.stage0_ric_path is None or self.vehicle.stage1_ric_path is None)
            ):
                raise ValueError("vehicle requires base_ric_path or stage0_ric_path + stage1_ric_path")
        return self


class V1TargetOnlyMissionRequest(BaseModel):
    mode: Literal["guided", "free_form"] = "guided"
    objectives: list[V1Objective] | None = None
    constraints: V1ConstraintSet
    allowed_propellants: V1AllowedPropellants | None = None
    vehicle: V1TargetOnlyVehicle
    solver_config: V1SolverConfig | None = None
    stage_count: int = Field(default=1, ge=1, le=2)
    output_dir: str | None = None
    tolerance_pct: float | None = Field(default=None, gt=0)
    split_ratios: list[float] | None = None
    cd_max: float | None = Field(default=None, gt=0)
    mach_max: float | None = Field(default=None, gt=0)
    cd_ramp: bool | None = None
    separation_delay_s: float | None = Field(default=None, ge=0)
    ignition_delay_s: float | None = Field(default=None, ge=0)
    allowed_propellant_families: list[str] | None = None
    allowed_propellant_names: list[str] | None = None
    preset_path: str | None = None
    weights: MissionTargetWeights | None = None
    search: MissionTargetSearch | None = None
    fast_mode: bool = True
    velocity_correction_factor: float = Field(default=1.0, gt=0)
    velocity_calibration: float = Field(default=1.0, gt=0)

    @model_validator(mode="after")
    def validate_objectives(self):
        if self.objectives:
            return self
        raise ValueError("Provide at least one objective")


class V1MissionTargetResult(BaseModel):
    openmotor_motorlib_result: dict[str, Any]
    inputs_hash: str
    engine_versions: dict[str, Any]


class V1ManualTestCandidate(BaseModel):
    propellant: str | None = None
    split_ratio: float | None = None
    predicted: dict[str, Any]
    artifacts: dict[str, str]
    objective_reports: list[V1ObjectiveReport] | None = None
    manual_openmotor: dict[str, Any] = Field(
        default_factory=lambda: {"status": "pending", "notes": None}
    )


class V1ManualTestReport(BaseModel):
    api_version: Literal["v1"] = "v1"
    job_kind: Literal["mission_target"] = "mission_target"
    job_id: str
    inputs_hash: str | None = None
    engine_versions: dict[str, Any] = Field(default_factory=dict)
    objectives: list[V1ObjectiveReport] | None = None
    summary: dict[str, Any] | None = None
    candidates: list[V1ManualTestCandidate] = Field(default_factory=list)
