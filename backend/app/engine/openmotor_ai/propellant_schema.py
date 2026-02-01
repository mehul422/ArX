from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class ValueWithUnits(BaseModel):
    value: float
    units: str


class BurnRateLaw(BaseModel):
    model: Literal["power_law"] = "power_law"
    a: ValueWithUnits
    n: ValueWithUnits
    reference_pressure: ValueWithUnits | None = None


class CombustionProperties(BaseModel):
    burn_rate_law: BurnRateLaw
    c_star: ValueWithUnits | None = None
    gamma: ValueWithUnits | None = None
    combustion_temperature: ValueWithUnits | None = None
    molecular_weight: ValueWithUnits | None = None


class PhysicalProperties(BaseModel):
    density: ValueWithUnits
    grain_porosity: ValueWithUnits | None = None


class ThermalProperties(BaseModel):
    flame_temperature: ValueWithUnits | None = None
    specific_heat: ValueWithUnits | None = None


class OperationalLimits(BaseModel):
    min_pressure: ValueWithUnits | None = None
    max_pressure: ValueWithUnits | None = None
    max_mass_flux: ValueWithUnits | None = None


class PropellantMetadata(BaseModel):
    created_by: str | None = None
    created_at: datetime | None = None
    validated: bool = False
    certification: Literal["none", "experimental", "research", "commercial"] = "none"
    validation_mode: Literal["realistic", "free_physics"] | None = None
    tags: list[str] = Field(default_factory=list)


class PropellantSchema(BaseModel):
    propellant_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    family: str | None = None
    source: Literal["user", "preset", "imported", "external_db"] = "user"
    description: str | None = None
    physical_properties: PhysicalProperties
    combustion_properties: CombustionProperties
    thermal_properties: ThermalProperties | None = None
    operational_limits: OperationalLimits | None = None
    metadata: PropellantMetadata = Field(default_factory=PropellantMetadata)

    @model_validator(mode="after")
    def validate_names(self):
        if not self.name.strip():
            raise ValueError("propellant name is required")
        return self


def propellant_to_spec(prop: PropellantSchema) -> "PropellantSpec":
    from app.engine.openmotor_ai.spec import PropellantSpec, PropellantTab

    burn = prop.combustion_properties.burn_rate_law
    gamma = prop.combustion_properties.gamma.value if prop.combustion_properties.gamma else 1.2
    temp = (
        prop.combustion_properties.combustion_temperature.value
        if prop.combustion_properties.combustion_temperature
        else 1700.0
    )
    molar = (
        prop.combustion_properties.molecular_weight.value
        if prop.combustion_properties.molecular_weight
        else 28.0
    )
    min_pressure = (
        prop.operational_limits.min_pressure.value
        if prop.operational_limits and prop.operational_limits.min_pressure
        else 1e5
    )
    max_pressure = (
        prop.operational_limits.max_pressure.value
        if prop.operational_limits and prop.operational_limits.max_pressure
        else 1e7
    )
    tab = PropellantTab(
        a=burn.a.value,
        n=burn.n.value,
        k=gamma,
        m=molar,
        t=temp,
        min_pressure_pa=min_pressure,
        max_pressure_pa=max_pressure,
    )
    return PropellantSpec(
        name=prop.name,
        density_kg_m3=prop.physical_properties.density.value,
        tabs=[tab],
    )


class MotorSchema(BaseModel):
    motor_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    stage: int
    case: dict[str, ValueWithUnits | str]
    grains: list[dict[str, object]]
    nozzle: dict[str, ValueWithUnits | float | str]
    propellant_ref: dict[str, str]
    metadata: dict[str, object] = Field(default_factory=dict)


class EngCurvePoint(BaseModel):
    time: float
    thrust: float


class EngArtifactSchema(BaseModel):
    motor_name: str
    manufacturer: str | None = None
    diameter: ValueWithUnits
    length: ValueWithUnits
    performance: dict[str, ValueWithUnits]
    thrust_curve: list[EngCurvePoint]
    metadata: dict[str, object] = Field(default_factory=dict)
