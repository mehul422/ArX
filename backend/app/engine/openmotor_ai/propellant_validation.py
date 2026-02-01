from __future__ import annotations

from app.engine.openmotor_ai.propellant_envelopes import envelope_for
from app.engine.openmotor_ai.propellant_schema import PropellantSchema, ValueWithUnits


def _unit_lower(value: ValueWithUnits | None) -> str:
    return value.units.strip().lower() if value else ""


def normalize_units(prop: PropellantSchema) -> PropellantSchema:
    # Density
    density = prop.physical_properties.density
    units = _unit_lower(density)
    if units in ("g/cc", "g/cm3", "g/cm^3"):
        density.value *= 1000.0
        density.units = "kg/m^3"
    elif units in ("kg/m3", "kg/m^3"):
        density.units = "kg/m^3"

    # Burn rate law coefficient
    a = prop.combustion_properties.burn_rate_law.a
    a_units = _unit_lower(a)
    if a_units in ("mm/s/mpa^n", "mm/s/mpa**n"):
        a.value = (a.value / 1000.0) / (1_000_000.0 ** prop.combustion_properties.burn_rate_law.n.value)
        a.units = "m/s/Pa^n"
    elif a_units in ("m/s/pa^n", "m/s/pa**n"):
        a.units = "m/s/Pa^n"

    # Pressure limits
    if prop.operational_limits:
        for field in ("min_pressure", "max_pressure"):
            value = getattr(prop.operational_limits, field)
            if value is None:
                continue
            u = _unit_lower(value)
            if u in ("mpa", "mpa_abs"):
                value.value *= 1_000_000.0
                value.units = "Pa"
            elif u in ("kpa", "kpa_abs"):
                value.value *= 1000.0
                value.units = "Pa"
            elif u in ("pa",):
                value.units = "Pa"
    return prop


def validate_physics(prop: PropellantSchema) -> list[str]:
    errors: list[str] = []
    density = prop.physical_properties.density.value
    a = prop.combustion_properties.burn_rate_law.a.value
    n = prop.combustion_properties.burn_rate_law.n.value
    gamma = prop.combustion_properties.gamma.value if prop.combustion_properties.gamma else None
    c_star = prop.combustion_properties.c_star.value if prop.combustion_properties.c_star else None
    tc = prop.combustion_properties.combustion_temperature.value if prop.combustion_properties.combustion_temperature else None

    if density <= 0:
        errors.append("density must be > 0")
    if a <= 0:
        errors.append("burn rate coefficient a must be > 0")
    if n <= 0:
        errors.append("burn rate exponent n must be > 0")
    if gamma is not None and gamma <= 1.0:
        errors.append("gamma must be > 1")
    if c_star is not None and c_star <= 500:
        errors.append("c_star too low (< 500 m/s)")
    if tc is not None and tc <= 800:
        errors.append("combustion temperature too low (< 800 K)")
    return errors


def validate_envelope(prop: PropellantSchema) -> list[str]:
    errors: list[str] = []
    env = envelope_for(prop.name, prop.family)
    if env is None:
        return errors

    density = prop.physical_properties.density.value
    a = prop.combustion_properties.burn_rate_law.a.value
    n = prop.combustion_properties.burn_rate_law.n.value
    gamma = prop.combustion_properties.gamma.value if prop.combustion_properties.gamma else None
    c_star = prop.combustion_properties.c_star.value if prop.combustion_properties.c_star else None
    tc = prop.combustion_properties.combustion_temperature.value if prop.combustion_properties.combustion_temperature else None

    if not (env.density_min <= density <= env.density_max):
        errors.append("density out of family envelope")
    if not (env.a_min <= a <= env.a_max):
        errors.append("burn rate coefficient a out of family envelope")
    if not (env.n_min <= n <= env.n_max):
        errors.append("burn rate exponent n out of family envelope")
    if gamma is not None and not (env.gamma_min <= gamma <= env.gamma_max):
        errors.append("gamma out of family envelope")
    if c_star is not None and not (env.c_star_min <= c_star <= env.c_star_max):
        errors.append("c_star out of family envelope")
    if tc is not None and not (env.tc_min <= tc <= env.tc_max):
        errors.append("combustion temperature out of family envelope")
    return errors


def validate_propellant(
    prop: PropellantSchema,
    mode: str = "realistic",
) -> tuple[PropellantSchema, list[str], list[str]]:
    errors = validate_physics(prop)
    warnings: list[str] = []
    prop.metadata.validation_mode = mode
    if mode == "realistic":
        envelope_errors = validate_envelope(prop)
        if envelope_errors:
            errors.extend(envelope_errors)
        if envelope_for(prop.name, prop.family) is None:
            warnings.append("no family envelope found; using physics-only validation")
    else:
        warnings.append("free_physics mode: propellant marked experimental")
        prop.metadata.validated = False
        if prop.metadata.certification == "none":
            prop.metadata.certification = "experimental"
        if "free_physics" not in prop.metadata.tags:
            prop.metadata.tags.append("free_physics")
    if not errors and mode == "realistic":
        prop.metadata.validated = True
    return prop, errors, warnings
