from __future__ import annotations

from app.engine.openrocket_like_legacy.models import ConstraintSet


def evaluate_constraints(
    metrics: dict[str, float],
    constraints: ConstraintSet,
    *,
    rocket_length_in: float | None = None,
) -> list[str]:
    violations: list[str] = []
    if constraints.max_pressure_psi is not None:
        peak_psi = metrics.get("peak_chamber_pressure", 0.0) / 6894.757
        if peak_psi > constraints.max_pressure_psi:
            violations.append(f"pressure>{constraints.max_pressure_psi}psi")
    if constraints.max_kn is not None:
        if metrics.get("peak_kn", 0.0) > constraints.max_kn:
            violations.append(f"kn>{constraints.max_kn}")
    if constraints.max_mass_flux is not None:
        if metrics.get("peak_mass_flux", 0.0) > constraints.max_mass_flux:
            violations.append(f"mass_flux>{constraints.max_mass_flux}")
    if constraints.max_vehicle_length_in is not None and rocket_length_in is not None:
        if rocket_length_in > constraints.max_vehicle_length_in:
            violations.append(f"length>{constraints.max_vehicle_length_in}in")
    return violations
