from __future__ import annotations

from dataclasses import dataclass
import math
import xml.etree.ElementTree as ET

from app.engine.openmotor_ai.motorlib_adapter import simulate_motorlib_with_result
from app.engine.openmotor_ai.spec import MotorSpec
from app.engine.openmotor_ai.eng_parser import EngData, load_eng
from app.engine.openmotor_ai.aero import CdTable

G0 = 9.80665
R_EARTH_M = 6371000.0


@dataclass(frozen=True)
class RocketMasses:
    stage0_dry_kg: float
    stage1_dry_kg: float
    ref_diameter_m: float


@dataclass(frozen=True)
class ApogeeResult:
    apogee_m: float
    max_velocity_m_s: float
    max_accel_m_s2: float
    burnout_time_s: float


def _float_or_zero(text: str | None) -> float:
    try:
        return float(text) if text is not None else 0.0
    except Exception:
        return 0.0


def load_rkt_masses(path: str) -> RocketMasses:
    tree = ET.parse(path)
    root = tree.getroot()

    stage3 = root.find(".//Stage3Parts")
    stage2 = root.find(".//Stage2Parts")
    if stage3 is None or stage2 is None:
        raise ValueError("RKT file missing Stage3Parts or Stage2Parts")

    def sum_known_mass(node: ET.Element) -> float:
        total = 0.0
        for mass_node in node.iter("KnownMass"):
            total += _float_or_zero(mass_node.text)
        # RKT uses grams for KnownMass
        return total / 1000.0

    def max_diameter(node: ET.Element) -> float:
        max_mm = 0.0
        for tag in ("OD", "BaseDia", "MotorDia"):
            for elem in node.iter(tag):
                max_mm = max(max_mm, _float_or_zero(elem.text))
        return max_mm / 1000.0

    stage1_dry = sum_known_mass(stage3)
    stage0_dry = sum_known_mass(stage2)
    ref_diameter = max(max_diameter(stage3), max_diameter(stage2))
    return RocketMasses(stage0_dry_kg=stage0_dry, stage1_dry_kg=stage1_dry, ref_diameter_m=ref_diameter)


def _isa_density(alt_m: float, sea_level_temp_k: float | None = None) -> float:
    # Simple ISA up to 86 km
    if alt_m < 0:
        alt_m = 0.0
    if alt_m <= 11000.0:
        t0 = sea_level_temp_k if sea_level_temp_k is not None else 288.15
        lapse = -0.0065
        p0 = 101325.0
        r = 287.05287
        t = t0 + lapse * alt_m
        p = p0 * (t / t0) ** (-G0 / (lapse * r))
        return p / (r * t)
    # Isothermal 11–20 km
    t = 216.65
    p11 = 22632.06
    r = 287.05287
    p = p11 * math.exp(-G0 * (alt_m - 11000.0) / (r * t))
    return p / (r * t)


def _isa_speed_of_sound(alt_m: float, sea_level_temp_k: float | None = None) -> float:
    if alt_m < 0:
        alt_m = 0.0
    if alt_m <= 11000.0:
        t0 = sea_level_temp_k if sea_level_temp_k is not None else 288.15
        lapse = -0.0065
        t = t0 + lapse * alt_m
    else:
        t = 216.65
    gamma = 1.4
    r = 287.05287
    return math.sqrt(gamma * r * t)


def _cd_from_mach(mach: float, cd_max: float, mach_max: float, ramp: bool) -> float:
    if not ramp or mach_max <= 0:
        return cd_max
    value = cd_max * min(max(mach, 0.0) / mach_max, 1.0)
    return max(value, 0.0)


def _cd_at(mach: float, cd_table: CdTable | None, cd_max: float, mach_max: float, cd_ramp: bool) -> float:
    if cd_table is not None:
        return cd_table.at(mach)
    return _cd_from_mach(mach, cd_max, mach_max, cd_ramp)


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i - 1]) / max(xs[i] - xs[i - 1], 1e-9)
            return ys[i - 1] + t * (ys[i] - ys[i - 1])
    return ys[-1]


def _simulate_stage(
    spec: MotorSpec,
    start_mass_kg: float,
    cd_max: float,
    mach_max: float,
    cd_ramp: bool,
    cd_table: CdTable | None,
    ref_area_m2: float,
    h0_m: float,
    v0_m_s: float,
    wind_speed_m_s: float = 0.0,
    sea_level_temp_k: float | None = None,
    launch_angle_deg: float = 0.0,
) -> tuple[ApogeeResult, float, float, float]:
    steps, sim = simulate_motorlib_with_result(spec)
    times = sim.channels["time"].getData()
    thrust = sim.channels["force"].getData()
    mass_flow = sim.channels["massFlow"].getData()
    mf = [frame[-1] if frame else 0.0 for frame in mass_flow]

    dt = spec.config.timestep_s
    h = h0_m
    v = v0_m_s
    mass = start_mass_kg
    max_v = v
    max_a = 0.0
    angle_rad = math.radians(max(min(launch_angle_deg, 89.0), -89.0))

    burn_end = times[-1]
    t = 0.0
    max_steps = int(max(1, burn_end / max(dt, 1e-3))) + 10
    steps = 0
    while t <= burn_end and mass > 0.0 and steps <= max_steps:
        thrust_t = _interp(t, times, thrust)
        mf_t = _interp(t, times, mf)
        v_rel = math.copysign(math.sqrt(v * v + wind_speed_m_s * wind_speed_m_s), v)
        rho = _isa_density(h, sea_level_temp_k)
        mach = abs(v_rel) / max(_isa_speed_of_sound(h, sea_level_temp_k), 1e-6)
        cd = _cd_at(mach, cd_table, cd_max, mach_max, cd_ramp)
        drag = 0.5 * rho * v_rel * v_rel * cd * ref_area_m2
        drag = drag if v_rel >= 0 else -drag
        g = G0 * (R_EARTH_M / (R_EARTH_M + h)) ** 2
        thrust_vert = thrust_t * math.cos(angle_rad)
        accel = (thrust_vert - drag) / mass - g
        v += accel * dt
        h += v * dt
        mass = max(mass - mf_t * dt, 1e-6)
        max_v = max(max_v, v)
        max_a = max(max_a, accel)
        t += dt
        steps += 1

    burn_result = ApogeeResult(apogee_m=h, max_velocity_m_s=max_v, max_accel_m_s2=max_a, burnout_time_s=burn_end)
    return burn_result, h, v, mass


def _coast(
    mass_kg: float,
    cd_max: float,
    mach_max: float,
    cd_ramp: bool,
    cd_table: CdTable | None,
    ref_area_m2: float,
    h0_m: float,
    v0_m_s: float,
    duration_s: float,
    timestep_s: float,
    wind_speed_m_s: float = 0.0,
    sea_level_temp_k: float | None = None,
) -> tuple[float, float]:
    h = h0_m
    v = v0_m_s
    t = 0.0
    dt = timestep_s
    if duration_s <= 0.0:
        return h, v
    max_steps = int(max(1, duration_s / max(dt, 1e-3))) + 1
    steps = 0
    while t <= duration_s and h >= 0 and steps <= max_steps:
        v_rel = math.copysign(math.sqrt(v * v + wind_speed_m_s * wind_speed_m_s), v)
        rho = _isa_density(h, sea_level_temp_k)
        mach = abs(v_rel) / max(_isa_speed_of_sound(h, sea_level_temp_k), 1e-6)
        cd = _cd_at(mach, cd_table, cd_max, mach_max, cd_ramp)
        drag = 0.5 * rho * v_rel * v_rel * cd * ref_area_m2
        g = G0 * (R_EARTH_M / (R_EARTH_M + h)) ** 2
        accel = (-drag / mass_kg) - g
        v += accel * dt
        h += v * dt
        t += dt
        steps += 1
    return h, v


def _simulate_two_stage_with_params(
    *,
    stage0: MotorSpec,
    stage1: MotorSpec,
    ref_diameter_m: float,
    stage0_dry_kg: float,
    stage1_dry_kg: float,
    cd_max: float,
    mach_max: float,
    cd_ramp: bool,
    cd_table: CdTable | None,
    total_mass_kg: float | None,
    separation_delay_s: float,
    ignition_delay_s: float,
    launch_altitude_m: float = 0.0,
    wind_speed_m_s: float = 0.0,
    temperature_k: float | None = None,
    rod_length_m: float = 0.0,
    launch_angle_deg: float = 0.0,
) -> ApogeeResult:
    ref_area = math.pi * (ref_diameter_m / 2.0) ** 2

    stage0_steps, stage0_sim = simulate_motorlib_with_result(stage0)
    stage1_steps, stage1_sim = simulate_motorlib_with_result(stage1)
    stage0_prop = stage0_sim.getPropellantMass()
    stage1_prop = stage1_sim.getPropellantMass()

    stage0_dry = stage0_dry_kg
    stage1_dry = stage1_dry_kg
    if total_mass_kg is not None:
        dry_total = max(stage0_dry + stage1_dry, 1e-6)
        desired_dry = max(total_mass_kg - (stage0_prop + stage1_prop), 1e-6)
        scale = desired_dry / dry_total
        stage0_dry *= scale
        stage1_dry *= scale

    angle_rad = math.radians(max(min(launch_angle_deg, 89.0), -89.0))
    start_alt_m = launch_altitude_m + max(rod_length_m, 0.0) * math.cos(angle_rad)
    m0 = stage0_dry + stage1_dry + stage0_prop + stage1_prop
    burn0, h, v, m_after0 = _simulate_stage(
        stage0,
        m0,
        cd_max,
        mach_max,
        cd_ramp,
        cd_table,
        ref_area,
        start_alt_m,
        0.0,
        wind_speed_m_s,
        temperature_k,
        launch_angle_deg,
    )

    dt = stage0.config.timestep_s
    h, v = _coast(
        mass_kg=m_after0,
        cd_max=cd_max,
        mach_max=mach_max,
        cd_ramp=cd_ramp,
        cd_table=cd_table,
        ref_area_m2=ref_area,
        h0_m=h,
        v0_m_s=v,
        duration_s=separation_delay_s,
        timestep_s=dt,
        wind_speed_m_s=wind_speed_m_s,
        sea_level_temp_k=temperature_k,
    )

    # Stage separation: drop stage0 dry mass
    m_stage1_start = max(m_after0 - stage0_dry, 1e-6)
    h, v = _coast(
        mass_kg=m_stage1_start,
        cd_max=cd_max,
        mach_max=mach_max,
        cd_ramp=cd_ramp,
        cd_table=cd_table,
        ref_area_m2=ref_area,
        h0_m=h,
        v0_m_s=v,
        duration_s=ignition_delay_s,
        timestep_s=dt,
        wind_speed_m_s=wind_speed_m_s,
        sea_level_temp_k=temperature_k,
    )
    burn1, h, v, m_after1 = _simulate_stage(
        stage1,
        m_stage1_start,
        cd_max,
        mach_max,
        cd_ramp,
        cd_table,
        ref_area,
        h,
        v,
        wind_speed_m_s,
        temperature_k,
        launch_angle_deg,
    )

    # Coast to apogee
    dt = stage1.config.timestep_s
    max_v = max(burn0.max_velocity_m_s, burn1.max_velocity_m_s)
    max_a = max(burn0.max_accel_m_s2, burn1.max_accel_m_s2)
    max_coast_steps = int(600.0 / max(dt, 1e-3))
    coast_steps = 0
    while v > 0 and h >= 0 and coast_steps <= max_coast_steps:
        v_rel = math.copysign(math.sqrt(v * v + wind_speed_m_s * wind_speed_m_s), v)
        rho = _isa_density(h, temperature_k)
        mach = abs(v_rel) / max(_isa_speed_of_sound(h, temperature_k), 1e-6)
        cd = _cd_at(mach, cd_table, cd_max, mach_max, cd_ramp)
        drag = 0.5 * rho * v_rel * v_rel * cd * ref_area
        g = G0 * (R_EARTH_M / (R_EARTH_M + h)) ** 2
        accel = (-drag / m_after1) - g
        v += accel * dt
        h += v * dt
        max_v = max(max_v, v)
        max_a = max(max_a, accel)
        coast_steps += 1

    return ApogeeResult(
        apogee_m=max(h, 0.0),
        max_velocity_m_s=max_v,
        max_accel_m_s2=max_a,
        burnout_time_s=burn0.burnout_time_s + burn1.burnout_time_s,
    )


def simulate_two_stage_apogee(
    stage0: MotorSpec,
    stage1: MotorSpec,
    rkt_path: str,
    cd_max: float = 0.5,
    mach_max: float = 2.0,
    cd_ramp: bool = False,
    cd_table: CdTable | None = None,
    total_mass_kg: float | None = None,
    separation_delay_s: float = 0.0,
    ignition_delay_s: float = 0.0,
    launch_altitude_m: float = 0.0,
    wind_speed_m_s: float = 0.0,
    temperature_k: float | None = None,
    rod_length_m: float = 0.0,
    launch_angle_deg: float = 0.0,
) -> ApogeeResult:
    masses = load_rkt_masses(rkt_path)
    return _simulate_two_stage_with_params(
        stage0=stage0,
        stage1=stage1,
        ref_diameter_m=masses.ref_diameter_m,
        stage0_dry_kg=masses.stage0_dry_kg,
        stage1_dry_kg=masses.stage1_dry_kg,
        cd_max=cd_max,
        mach_max=mach_max,
        cd_ramp=cd_ramp,
        cd_table=cd_table,
        total_mass_kg=total_mass_kg,
        separation_delay_s=separation_delay_s,
        ignition_delay_s=ignition_delay_s,
        launch_altitude_m=launch_altitude_m,
        wind_speed_m_s=wind_speed_m_s,
        temperature_k=temperature_k,
        rod_length_m=rod_length_m,
        launch_angle_deg=launch_angle_deg,
    )


def simulate_two_stage_apogee_params(
    *,
    stage0: MotorSpec,
    stage1: MotorSpec,
    ref_diameter_m: float,
    stage0_dry_kg: float,
    stage1_dry_kg: float,
    cd_max: float = 0.5,
    mach_max: float = 2.0,
    cd_ramp: bool = False,
    cd_table: CdTable | None = None,
    total_mass_kg: float | None = None,
    separation_delay_s: float = 0.0,
    ignition_delay_s: float = 0.0,
    launch_altitude_m: float = 0.0,
    wind_speed_m_s: float = 0.0,
    temperature_k: float | None = None,
    rod_length_m: float = 0.0,
    launch_angle_deg: float = 0.0,
) -> ApogeeResult:
    return _simulate_two_stage_with_params(
        stage0=stage0,
        stage1=stage1,
        ref_diameter_m=ref_diameter_m,
        stage0_dry_kg=stage0_dry_kg,
        stage1_dry_kg=stage1_dry_kg,
        cd_max=cd_max,
        mach_max=mach_max,
        cd_ramp=cd_ramp,
        cd_table=cd_table,
        total_mass_kg=total_mass_kg,
        separation_delay_s=separation_delay_s,
        ignition_delay_s=ignition_delay_s,
        launch_altitude_m=launch_altitude_m,
        wind_speed_m_s=wind_speed_m_s,
        temperature_k=temperature_k,
        rod_length_m=rod_length_m,
        launch_angle_deg=launch_angle_deg,
    )


def simulate_single_stage_apogee_params(
    *,
    stage: MotorSpec,
    ref_diameter_m: float,
    total_mass_kg: float,
    cd_max: float = 0.5,
    mach_max: float = 2.0,
    cd_ramp: bool = False,
    cd_table: CdTable | None = None,
    launch_altitude_m: float = 0.0,
    wind_speed_m_s: float = 0.0,
    temperature_k: float | None = None,
    rod_length_m: float = 0.0,
    launch_angle_deg: float = 0.0,
) -> ApogeeResult:
    if total_mass_kg <= 0:
        raise ValueError("total_mass_kg must be positive")
    ref_area = math.pi * (ref_diameter_m / 2.0) ** 2

    steps, sim = simulate_motorlib_with_result(stage)
    prop_mass = sim.getPropellantMass()
    dry_mass = max(total_mass_kg - prop_mass, 1e-6)
    start_mass = dry_mass + prop_mass

    angle_rad = math.radians(max(min(launch_angle_deg, 89.0), -89.0))
    start_alt_m = launch_altitude_m + max(rod_length_m, 0.0) * math.cos(angle_rad)
    burn, h, v, m_after = _simulate_stage(
        stage,
        start_mass,
        cd_max,
        mach_max,
        cd_ramp,
        cd_table,
        ref_area,
        start_alt_m,
        0.0,
        wind_speed_m_s,
        temperature_k,
        launch_angle_deg,
    )

    dt = stage.config.timestep_s
    max_v = burn.max_velocity_m_s
    max_a = burn.max_accel_m_s2
    coast_steps = 0
    while v > 0 and h >= 0 and coast_steps <= int(600.0 / max(dt, 1e-3)):
        v_rel = math.copysign(math.sqrt(v * v + wind_speed_m_s * wind_speed_m_s), v)
        rho = _isa_density(h, temperature_k)
        mach = abs(v_rel) / max(_isa_speed_of_sound(h, temperature_k), 1e-6)
        cd = _cd_at(mach, cd_table, cd_max, mach_max, cd_ramp)
        drag = 0.5 * rho * v_rel * v_rel * cd * ref_area
        g = G0 * (R_EARTH_M / (R_EARTH_M + h)) ** 2
        accel = (-drag / m_after) - g
        v += accel * dt
        h += v * dt
        max_v = max(max_v, v)
        max_a = max(max_a, accel)
        coast_steps += 1

    return ApogeeResult(
        apogee_m=max(h, 0.0),
        max_velocity_m_s=max_v,
        max_accel_m_s2=max_a,
        burnout_time_s=burn.burnout_time_s,
    )


def _burn_from_eng(
    eng: EngData,
    start_mass_kg: float,
    prop_mass_kg: float,
    cd_max: float,
    mach_max: float,
    cd_ramp: bool,
    cd_table: CdTable | None,
    ref_area_m2: float,
    h0_m: float,
    v0_m_s: float,
    timestep_s: float,
) -> tuple[ApogeeResult, float, float, float]:
    times = [t for t, _ in eng.curve]
    thrust = [f for _, f in eng.curve]
    burn_time = times[-1]
    dt = timestep_s
    h = h0_m
    v = v0_m_s
    mass = start_mass_kg
    max_v = v
    max_a = 0.0
    mass_flow = prop_mass_kg / max(burn_time, 1e-6)

    t = 0.0
    while t <= burn_time and mass > 0.0:
        thrust_t = _interp(t, times, thrust)
        rho = _isa_density(h)
        mach = abs(v) / max(_isa_speed_of_sound(h), 1e-6)
        cd = _cd_at(mach, cd_table, cd_max, mach_max, cd_ramp)
        drag = 0.5 * rho * v * v * cd * ref_area_m2
        drag = drag if v >= 0 else -drag
        g = G0 * (R_EARTH_M / (R_EARTH_M + h)) ** 2
        accel = (thrust_t - drag) / mass - g
        v += accel * dt
        h += v * dt
        mass = max(mass - mass_flow * dt, 1e-6)
        max_v = max(max_v, v)
        max_a = max(max_a, accel)
        t += dt

    burn_result = ApogeeResult(apogee_m=h, max_velocity_m_s=max_v, max_accel_m_s2=max_a, burnout_time_s=burn_time)
    return burn_result, h, v, mass


def simulate_two_stage_apogee_from_eng(
    stage0_eng_path: str,
    stage1_eng_path: str,
    rkt_path: str,
    cd_max: float,
    mach_max: float,
    cd_ramp: bool = False,
    cd_table: CdTable | None = None,
    total_mass_kg: float | None = None,
    timestep_s: float = 0.03,
    separation_delay_s: float = 0.0,
    ignition_delay_s: float = 0.0,
) -> ApogeeResult:
    eng0 = load_eng(stage0_eng_path)
    eng1 = load_eng(stage1_eng_path)
    prop0 = eng0.header.header_values[0] if eng0.header.header_values else 0.0
    prop1 = eng1.header.header_values[0] if eng1.header.header_values else 0.0

    masses = load_rkt_masses(rkt_path)
    stage0_dry = masses.stage0_dry_kg
    stage1_dry = masses.stage1_dry_kg
    if total_mass_kg is not None:
        dry_total = max(stage0_dry + stage1_dry, 1e-6)
        desired_dry = max(total_mass_kg - (prop0 + prop1), 1e-6)
        scale = desired_dry / dry_total
        stage0_dry *= scale
        stage1_dry *= scale

    ref_area = math.pi * (masses.ref_diameter_m / 2.0) ** 2
    m0 = stage0_dry + stage1_dry + prop0 + prop1

    burn0, h, v, m_after0 = _burn_from_eng(
        eng0, m0, prop0, cd_max, mach_max, cd_ramp, cd_table, ref_area, 0.0, 0.0, timestep_s
    )

    h, v = _coast(
        mass_kg=m_after0,
        cd_max=cd_max,
        mach_max=mach_max,
        cd_ramp=cd_ramp,
        cd_table=cd_table,
        ref_area_m2=ref_area,
        h0_m=h,
        v0_m_s=v,
        duration_s=separation_delay_s,
        timestep_s=timestep_s,
    )

    m_stage1_start = max(m_after0 - stage0_dry, 1e-6)
    h, v = _coast(
        mass_kg=m_stage1_start,
        cd_max=cd_max,
        mach_max=mach_max,
        cd_ramp=cd_ramp,
        cd_table=cd_table,
        ref_area_m2=ref_area,
        h0_m=h,
        v0_m_s=v,
        duration_s=ignition_delay_s,
        timestep_s=timestep_s,
    )
    burn1, h, v, m_after1 = _burn_from_eng(
        eng1, m_stage1_start, prop1, cd_max, mach_max, cd_ramp, cd_table, ref_area, h, v, timestep_s
    )

    dt = timestep_s
    max_v = max(burn0.max_velocity_m_s, burn1.max_velocity_m_s)
    max_a = max(burn0.max_accel_m_s2, burn1.max_accel_m_s2)
    coast_steps = 0
    while v > 0 and h >= 0 and coast_steps <= int(600.0 / max(dt, 1e-3)):
        rho = _isa_density(h)
        mach = abs(v) / max(_isa_speed_of_sound(h), 1e-6)
        cd = _cd_at(mach, cd_table, cd_max, mach_max, cd_ramp)
        drag = 0.5 * rho * v * v * cd * ref_area
        g = G0 * (R_EARTH_M / (R_EARTH_M + h)) ** 2
        accel = (-drag / m_after1) - g
        v += accel * dt
        h += v * dt
        max_v = max(max_v, v)
        max_a = max(max_a, accel)
        coast_steps += 1

    return ApogeeResult(
        apogee_m=max(h, 0.0),
        max_velocity_m_s=max_v,
        max_accel_m_s2=max_a,
        burnout_time_s=burn0.burnout_time_s + burn1.burnout_time_s,
    )


def compare_constant_vs_table(
    stage0_eng_path: str,
    stage1_eng_path: str,
    rkt_path: str,
    constant_cd: float,
    cd_table: CdTable,
    mach_max: float,
    total_mass_kg: float | None = None,
    separation_delay_s: float = 0.0,
    ignition_delay_s: float = 0.0,
) -> dict[str, float]:
    const = simulate_two_stage_apogee_from_eng(
        stage0_eng_path=stage0_eng_path,
        stage1_eng_path=stage1_eng_path,
        rkt_path=rkt_path,
        cd_max=constant_cd,
        mach_max=mach_max,
        cd_ramp=False,
        cd_table=None,
        total_mass_kg=total_mass_kg,
        separation_delay_s=separation_delay_s,
        ignition_delay_s=ignition_delay_s,
    )
    table = simulate_two_stage_apogee_from_eng(
        stage0_eng_path=stage0_eng_path,
        stage1_eng_path=stage1_eng_path,
        rkt_path=rkt_path,
        cd_max=constant_cd,
        mach_max=mach_max,
        cd_ramp=False,
        cd_table=cd_table,
        total_mass_kg=total_mass_kg,
        separation_delay_s=separation_delay_s,
        ignition_delay_s=ignition_delay_s,
    )
    return {
        "constant_apogee_ft": const.apogee_m * 3.28084,
        "table_apogee_ft": table.apogee_m * 3.28084,
        "apogee_error_ft": abs(table.apogee_m - const.apogee_m) * 3.28084,
    }
