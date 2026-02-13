from __future__ import annotations

from app.module_r.schemas import AutoBuildConstraints, RocketAssembly, TelemetryMass


class FlightReadyValidationError(ValueError):
    pass


def _total_payload_mass(assembly: RocketAssembly) -> float:
    total = 0.0
    for tube in assembly.body_tubes:
        for child in tube.children:
            if isinstance(child, TelemetryMass):
                total += child.mass_kg
    return total


def validate_basic_flight_ready(
    assembly: RocketAssembly,
    constraints: AutoBuildConstraints,
    *,
    motor_diameter_m: float,
    motor_length_m: float,
) -> None:
    if assembly.global_diameter_m <= motor_diameter_m:
        raise FlightReadyValidationError("motor does not fit inside global diameter")

    for stage in assembly.stages:
        mount = stage.motor_mount
        if mount.length_m < motor_length_m:
            raise FlightReadyValidationError("motor mount length is too short")
        if mount.outer_diameter_m >= stage.diameter_m:
            raise FlightReadyValidationError("motor mount does not fit inside stage")
        if mount.inner_diameter_m is not None and mount.inner_diameter_m < motor_diameter_m:
            raise FlightReadyValidationError("motor does not fit inside motor mount")

    total_length = assembly.nose_cone.length_m
    total_length += sum(stage.length_m for stage in assembly.stages)
    total_length += sum(tube.length_m for tube in assembly.body_tubes)
    if total_length > constraints.upper_length_m:
        raise FlightReadyValidationError("total length exceeds upper bound")

    total_mass = _total_payload_mass(assembly)
    if total_mass > constraints.upper_mass_kg:
        raise FlightReadyValidationError("total mass exceeds upper bound")

    for fin in assembly.fin_sets:
        if fin.span_m < assembly.global_diameter_m * 0.25:
            raise FlightReadyValidationError("fin span too small for stability")
