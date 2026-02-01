from __future__ import annotations

from app.engine.openmotor_ai.ballistics import TimeStep, thrust_curve
from app.engine.openmotor_ai.eng_parser import EngData, EngHeader
from app.engine.openmotor_ai.spec import MotorSpec


def build_eng(
    spec: MotorSpec,
    steps: list[TimeStep],
    designation: str = "AI-BATES",
    manufacturer: str = "openmotor-ai",
) -> EngData:
    diameter_mm = spec.grains[0].diameter_m * 1000.0
    length_mm = sum(grain.length_m for grain in spec.grains) * 1000.0
    propellant_mass_kg = 0.0
    for grain in spec.grains:
        outer_radius = grain.diameter_m / 2.0
        inner_radius = grain.core_diameter_m / 2.0
        propellant_mass_kg += (
            3.141592653589793
            * (outer_radius**2 - inner_radius**2)
            * grain.length_m
            * spec.propellant.density_kg_m3
        )
    header = EngHeader(
        designation=designation,
        diameter_mm=diameter_mm,
        length_mm=length_mm,
        motor_type="P",
        header_values=[propellant_mass_kg, propellant_mass_kg],
        manufacturer=manufacturer,
    )
    return EngData(header=header, curve=thrust_curve(steps))
