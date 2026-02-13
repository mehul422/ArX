from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PropellantFamily(StrEnum):
    COMMERCIAL = "commercial"
    SUGAR = "sugar"
    EXPERIMENTAL = "experimental"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PropellantLabel:
    name: str
    family: PropellantFamily = PropellantFamily.UNKNOWN
    source: str = "user"


class GrainGeometryType(StrEnum):
    BATES = "BATES"
    FINOCYL = "Finocyl"
    MOON = "Moon"
    SLOT = "Slot"
    STAR = "Star"
    CUSTOM = "Custom"


@dataclass(frozen=True)
class GrainGeometry:
    type: GrainGeometryType
    params: dict[str, float]


@dataclass(frozen=True)
class NozzleConfig:
    throat_diameter_m: float
    exit_diameter_m: float
    throat_length_m: float = 0.0
    conv_angle_deg: float = 35.0
    div_angle_deg: float = 12.0
    efficiency: float = 1.0
    erosion_coeff: float = 0.0
    slag_coeff: float = 0.0


@dataclass(frozen=True)
class MotorStageDefinition:
    stage_id: str
    grain_geometry: GrainGeometry
    nozzle: NozzleConfig
    propellant_label: PropellantLabel
    propellant_physics: dict[str, Any] | None = None


@dataclass(frozen=True)
class ConstraintSet:
    max_pressure_psi: float | None = None
    max_kn: float | None = None
    max_mass_flux: float | None = None
    max_vehicle_length_in: float | None = None
    soft_constraints: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Objective:
    name: str
    target: float
    tolerance_pct: float | None = None
    weight: float | None = None


@dataclass(frozen=True)
class ObjectiveReport:
    name: str
    target: float
    predicted: float
    error_pct: float
    units: str | None = None


@dataclass(frozen=True)
class ArtifactRecord:
    kind: str
    path: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MotorRecord:
    designation: str
    diameter_m: float
    length_m: float
    motor_type: str
    manufacturer: str | None
    propellant_label: str | None
    delays_s: list[float]
    thrust_curve: list[tuple[float, float]]
    source: str
    metadata: dict[str, Any] = field(default_factory=dict)

