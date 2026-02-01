from __future__ import annotations

from dataclasses import dataclass

from app.engine.openmotor_ai.ork_reader import RocketDimensions
from app.engine.openmotor_ai.cdx1_reader import RasaeroDimensions


@dataclass(frozen=True)
class DesignConstraints:
    max_pressure_psi: float
    max_kn: float
    port_throat_min: float
    port_throat_max: float
    max_mass_flux: float
    min_rocket_diameter_in: float
    max_rocket_length_ft: float


def validate_rocket_constraints(dimensions: RocketDimensions, constraints: DesignConstraints) -> list[str]:
    failures: list[str] = []
    diameter_in = dimensions.max_diameter_m * 39.3700787402
    length_ft = dimensions.length_m * 3.280839895

    if diameter_in <= constraints.min_rocket_diameter_in:
        failures.append(
            f"Rocket diameter {diameter_in:.2f} in <= minimum {constraints.min_rocket_diameter_in:.2f} in"
        )
    if length_ft > constraints.max_rocket_length_ft:
        failures.append(
            f"Rocket length {length_ft:.2f} ft > maximum {constraints.max_rocket_length_ft:.2f} ft"
        )
    return failures


def validate_rasaero_constraints(dimensions: RasaeroDimensions, constraints: DesignConstraints) -> list[str]:
    failures: list[str] = []
    if dimensions.max_diameter_in <= constraints.min_rocket_diameter_in:
        failures.append(
            f"Rocket diameter {dimensions.max_diameter_in:.2f} in <= minimum {constraints.min_rocket_diameter_in:.2f} in"
        )
    length_ft = dimensions.length_in / 12.0
    if length_ft > constraints.max_rocket_length_ft:
        failures.append(
            f"Rocket length {length_ft:.2f} ft > maximum {constraints.max_rocket_length_ft:.2f} ft"
        )
    return failures
