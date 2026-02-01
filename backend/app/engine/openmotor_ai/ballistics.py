from __future__ import annotations

from dataclasses import dataclass
from math import pi, sqrt
import os

from app.engine.openmotor_ai.spec import BATESGrain, MotorSpec, PropellantTab

G0 = 9.80665


@dataclass(frozen=True)
class TimeStep:
    time_s: float
    chamber_pressure_pa: float
    thrust_n: float
    mass_flow_kg_s: float
    kn: float
    port_area_m2: float


def _select_tab(tabs: list[PropellantTab], pressure_pa: float) -> PropellantTab:
    for tab in tabs:
        if tab.min_pressure_pa <= pressure_pa <= tab.max_pressure_pa:
            return tab
    return tabs[-1]


def _c_star(tab: PropellantTab) -> float:
    if tab.m <= 0 or tab.t <= 0 or tab.k <= 1.0:
        return 1500.0
    r_specific = 8314.462618 / tab.m
    gamma = tab.k
    term = (2.0 / (gamma + 1.0)) ** ((gamma + 1.0) / (2.0 * (gamma - 1.0)))
    return sqrt(r_specific * tab.t) / (gamma * term)


def _area_ratio_from_mach(mach: float, gamma: float) -> float:
    term = (2.0 / (gamma + 1.0)) * (1.0 + (gamma - 1.0) * 0.5 * mach * mach)
    return (1.0 / mach) * term ** ((gamma + 1.0) / (2.0 * (gamma - 1.0)))


def _exit_mach(area_ratio: float, gamma: float) -> float:
    lo, hi = 1e-6, 20.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        value = _area_ratio_from_mach(mid, gamma)
        if value > area_ratio:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _thrust_coefficient(
    gamma: float, area_ratio: float, amb_pressure_pa: float, chamber_pressure_pa: float
) -> float:
    mach_e = _exit_mach(area_ratio, gamma)
    pe_over_pc = (1.0 + (gamma - 1.0) * 0.5 * mach_e * mach_e) ** (
        -gamma / (gamma - 1.0)
    )
    term1 = sqrt(
        (2.0 * gamma * gamma / (gamma - 1.0))
        * (2.0 / (gamma + 1.0)) ** ((gamma + 1.0) / (gamma - 1.0))
        * (1.0 - pe_over_pc ** ((gamma - 1.0) / gamma))
    )
    term2 = (pe_over_pc - amb_pressure_pa / chamber_pressure_pa) * area_ratio
    return term1 + term2


def _burning_area(grain: BATESGrain, web: float) -> tuple[float, float, float]:
    outer_radius = grain.diameter_m / 2.0
    core_radius = grain.core_diameter_m / 2.0 + web
    if core_radius >= outer_radius:
        return 0.0, 0.0, 0.0
    length = max(0.0, grain.length_m - _end_regression(grain) * web * 2.0)
    if length <= 0:
        return 0.0, 0.0, 0.0
    core_area = pi * core_radius * 2.0 * length
    end_area = pi * (outer_radius**2 - core_radius**2) * _burning_end_count(grain)
    port_area = pi * core_radius * core_radius
    return core_area + end_area, port_area, length


def _burning_end_count(grain: BATESGrain) -> int:
    ends = grain.inhibited_ends.lower()
    if ends in ("both", "both ends"):
        return 0
    if ends in ("fore", "aft"):
        return 1
    return 2


def _end_regression(grain: BATESGrain) -> float:
    ends = grain.inhibited_ends.lower()
    if ends in ("both", "both ends"):
        return 0.0
    if ends in ("fore", "aft"):
        return 0.5
    return 1.0


def _simulate_ballistics_internal(spec: MotorSpec) -> list[TimeStep]:
    throat_area = pi * (spec.nozzle.throat_diameter_m / 2.0) ** 2
    exit_area = pi * (spec.nozzle.exit_diameter_m / 2.0) ** 2
    area_ratio = exit_area / throat_area if throat_area > 0 else 1.0
    gamma = spec.propellant.tabs[0].k
    rho = spec.propellant.density_kg_m3

    time = 0.0
    web = 0.0
    steps: list[TimeStep] = []

    for _ in range(20000):
        total_aburn = 0.0
        total_port = 0.0
        for grain in spec.grains:
            aburn, port_area, _ = _burning_area(grain, web)
            total_aburn += aburn
            total_port += port_area

        if total_aburn <= 0.0 or total_port <= 0.0:
            break

        # pressure estimate using current tab
        tab = spec.propellant.tabs[0]
        c_star = _c_star(tab)
        chamber_pressure = (
            rho * total_aburn * tab.a * c_star / throat_area
        ) ** (1.0 / (1.0 - tab.n))
        tab = _select_tab(spec.propellant.tabs, chamber_pressure)
        c_star = _c_star(tab)
        chamber_pressure = (
            rho * total_aburn * tab.a * c_star / throat_area
        ) ** (1.0 / (1.0 - tab.n))

        burn_rate = tab.a * chamber_pressure**tab.n
        cf = _thrust_coefficient(
            gamma, area_ratio, spec.config.amb_pressure_pa, chamber_pressure
        )
        thrust = cf * chamber_pressure * throat_area * spec.nozzle.efficiency
        mass_flow = chamber_pressure * throat_area / c_star
        kn = total_aburn / throat_area

        steps.append(
            TimeStep(
                time_s=time,
                chamber_pressure_pa=chamber_pressure,
                thrust_n=thrust,
                mass_flow_kg_s=mass_flow,
                kn=kn,
                port_area_m2=total_port,
            )
        )

        time += spec.config.timestep_s
        web += burn_rate * spec.config.timestep_s

        if chamber_pressure >= spec.config.max_pressure_pa:
            break
        if burn_rate * spec.config.timestep_s <= spec.config.burnout_web_threshold_m:
            break
        if thrust <= spec.config.burnout_thrust_threshold_n:
            break

    return steps


def simulate_ballistics(spec: MotorSpec) -> list[TimeStep]:
    if os.getenv("OPENMOTOR_AI_USE_INTERNAL") == "1":
        return _simulate_ballistics_internal(spec)
    from app.engine.openmotor_ai.motorlib_adapter import simulate_motorlib

    return simulate_motorlib(spec)


def aggregate_metrics(spec: MotorSpec, steps: list[TimeStep]) -> dict[str, float]:
    if not steps:
        return {}
    burn_time = steps[-1].time_s
    if burn_time <= 0.0:
        burn_time = spec.config.timestep_s
    total_impulse = 0.0
    total_pressure = 0.0
    peak_pressure = 0.0
    peak_kn = 0.0
    peak_mass_flux = 0.0
    for idx in range(1, len(steps)):
        t0, f0 = steps[idx - 1].time_s, steps[idx - 1].thrust_n
        t1, f1 = steps[idx].time_s, steps[idx].thrust_n
        total_impulse += (t1 - t0) * (f0 + f1) * 0.5
    if len(steps) == 1:
        total_impulse = steps[0].thrust_n * burn_time
    for step in steps:
        total_pressure += step.chamber_pressure_pa
        peak_pressure = max(peak_pressure, step.chamber_pressure_pa)
        peak_kn = max(peak_kn, step.kn)
        mass_flux = step.mass_flow_kg_s / step.port_area_m2
        peak_mass_flux = max(peak_mass_flux, mass_flux)

    avg_pressure = total_pressure / len(steps)
    ideal_cf = _thrust_coefficient(
        spec.propellant.tabs[0].k,
        (spec.nozzle.exit_diameter_m / spec.nozzle.throat_diameter_m) ** 2,
        spec.config.amb_pressure_pa,
        max(steps[0].chamber_pressure_pa, 1.0),
    )
    delivered_cf = (total_impulse / burn_time) / (
        avg_pressure * pi * (spec.nozzle.throat_diameter_m / 2.0) ** 2
    )

    prop_volume = sum(
        pi
        * ((grain.diameter_m / 2.0) ** 2 - (grain.core_diameter_m / 2.0) ** 2)
        * grain.length_m
        for grain in spec.grains
    )
    prop_mass = prop_volume * spec.propellant.density_kg_m3
    prop_length = sum(grain.length_m for grain in spec.grains)
    volume_loading = prop_volume / (
        pi * (spec.grains[0].diameter_m / 2.0) ** 2 * prop_length
    )

    throat_area = pi * (spec.nozzle.throat_diameter_m / 2.0) ** 2
    port_throat_ratio = steps[0].port_area_m2 / throat_area

    return {
        "total_impulse": total_impulse,
        "burn_time": burn_time,
        "average_chamber_pressure": avg_pressure,
        "peak_chamber_pressure": peak_pressure,
        "initial_kn": steps[0].kn,
        "peak_kn": peak_kn,
        "ideal_thrust_coefficient": ideal_cf,
        "propellant_mass": prop_mass,
        "propellant_length": prop_length,
        "volume_loading": volume_loading,
        "port_to_throat_ratio": port_throat_ratio,
        "peak_mass_flux": peak_mass_flux,
        "delivered_thrust_coefficient": delivered_cf,
        "delivered_specific_impulse": total_impulse / max(prop_mass * G0, 1e-6),
    }


def thrust_curve(steps: list[TimeStep]) -> list[tuple[float, float]]:
    if not steps:
        return []
    curve = [(step.time_s, step.thrust_n) for step in steps]
    last_time = curve[-1][0]
    if curve[-1][1] != 0.0:
        curve.append((last_time + steps[-1].time_s, 0.0))
    return curve
