from __future__ import annotations

from app.engine.openmotor_ai.spec import MotorSpec


def _format_number(value: float) -> str:
    if abs(value) >= 1000:
        return f"{value:.1f}".rstrip("0").rstrip(".")
    return f"{value:.6g}"


def _format_half_inches(value_m: float) -> str:
    inches = value_m / 0.0254
    rounded_in = round(inches * 2.0) / 2.0
    rounded_m = rounded_in * 0.0254
    return f"{rounded_m:.6g}"


def _format_half_unit(value: float) -> str:
    rounded = round(value * 2.0) / 2.0
    if abs(rounded - int(rounded)) < 1e-9:
        return str(int(rounded))
    return f"{rounded:.1f}"


def build_ric(spec: MotorSpec) -> str:
    lines: list[str] = []
    lines.append("data:")
    lines.append("  config:")
    lines.append(f"    ambPressure: {_format_number(spec.config.amb_pressure_pa)}")
    lines.append(f"    burnoutThrustThres: {_format_number(spec.config.burnout_thrust_threshold_n)}")
    lines.append(f"    burnoutWebThres: {_format_number(spec.config.burnout_web_threshold_m)}")
    lines.append(f"    mapDim: {spec.config.map_dim}")
    lines.append(f"    maxMassFlux: {_format_number(spec.config.max_mass_flux_kg_m2_s)}")
    lines.append(f"    maxPressure: {_format_number(spec.config.max_pressure_pa)}")
    lines.append(f"    minPortThroat: {_format_number(spec.config.min_port_throat_ratio)}")
    lines.append(f"    timestep: {_format_number(spec.config.timestep_s)}")
    lines.append("  grains:")
    for grain in spec.grains:
        lines.append("  - properties:")
        lines.append(f"      coreDiameter: {_format_half_inches(grain.core_diameter_m)}")
        lines.append(f"      diameter: {_format_half_inches(grain.diameter_m)}")
        lines.append(f"      inhibitedEnds: {grain.inhibited_ends}")
        lines.append(f"      length: {_format_half_inches(grain.length_m)}")
        lines.append("    type: BATES")
    lines.append("  nozzle:")
    lines.append(f"    convAngle: {_format_half_unit(spec.nozzle.conv_angle_deg)}")
    lines.append(f"    divAngle: {_format_half_unit(spec.nozzle.div_angle_deg)}")
    lines.append(f"    efficiency: {_format_number(spec.nozzle.efficiency)}")
    lines.append(f"    erosionCoeff: {_format_number(spec.nozzle.erosion_coeff)}")
    lines.append(f"    exit: {_format_half_inches(spec.nozzle.exit_diameter_m)}")
    lines.append(f"    slagCoeff: {_format_number(spec.nozzle.slag_coeff)}")
    lines.append(f"    throat: {_format_half_inches(spec.nozzle.throat_diameter_m)}")
    lines.append(f"    throatLength: {_format_half_inches(spec.nozzle.throat_length_m)}")
    lines.append("  propellant:")
    lines.append(f"    density: {_format_number(spec.propellant.density_kg_m3)}")
    lines.append(f"    name: {spec.propellant.name}")
    lines.append("    tabs:")
    for tab in spec.propellant.tabs:
        lines.append(f"    - a: {_format_number(tab.a)}")
        lines.append(f"      k: {_format_number(tab.k)}")
        lines.append(f"      m: {_format_number(tab.m)}")
        lines.append(f"      maxPressure: {_format_number(tab.max_pressure_pa)}")
        lines.append(f"      minPressure: {_format_number(tab.min_pressure_pa)}")
        lines.append(f"      n: {_format_number(tab.n)}")
        lines.append(f"      t: {_format_number(tab.t)}")
    lines.append("type: !!python/object/apply:uilib.fileIO.fileTypes")
    lines.append("- 3")
    lines.append("version: !!python/tuple")
    lines.append("- 0")
    lines.append("- 5")
    lines.append("- 0")
    return "\n".join(lines) + "\n"
