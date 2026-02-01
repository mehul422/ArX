from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.engine.openmotor_ai.ric_parser import RicData


@dataclass(frozen=True)
class PropellantTab:
    a: float
    n: float
    k: float
    m: float
    t: float
    min_pressure_pa: float
    max_pressure_pa: float


@dataclass(frozen=True)
class PropellantSpec:
    name: str
    density_kg_m3: float
    tabs: list[PropellantTab]


@dataclass(frozen=True)
class BATESGrain:
    diameter_m: float
    core_diameter_m: float
    length_m: float
    inhibited_ends: str


@dataclass(frozen=True)
class NozzleSpec:
    throat_diameter_m: float
    exit_diameter_m: float
    throat_length_m: float
    conv_angle_deg: float
    div_angle_deg: float
    efficiency: float
    erosion_coeff: float
    slag_coeff: float


@dataclass(frozen=True)
class MotorConfig:
    amb_pressure_pa: float
    burnout_thrust_threshold_n: float
    burnout_web_threshold_m: float
    map_dim: int
    max_mass_flux_kg_m2_s: float
    max_pressure_pa: float
    min_port_throat_ratio: float
    timestep_s: float


@dataclass(frozen=True)
class MotorSpec:
    config: MotorConfig
    propellant: PropellantSpec
    grains: list[BATESGrain]
    nozzle: NozzleSpec


def _require_bates(grains: list[dict[str, Any]]) -> list[BATESGrain]:
    parsed: list[BATESGrain] = []
    for grain in grains:
        grain_type = grain.get("type")
        if grain_type != "BATES":
            raise ValueError(f"Unsupported grain type: {grain_type}")
        props = grain.get("properties", {})
        parsed.append(
            BATESGrain(
                diameter_m=float(props.get("diameter", 0.0)),
                core_diameter_m=float(props.get("coreDiameter", 0.0)),
                length_m=float(props.get("length", 0.0)),
                inhibited_ends=str(props.get("inhibitedEnds", "")),
            )
        )
    return parsed


def _parse_propellant(propellant: dict[str, Any]) -> PropellantSpec:
    name = str(propellant.get("name", ""))
    density = float(propellant.get("density", 0.0))
    tabs = []
    for tab in propellant.get("tabs", []) or []:
        tabs.append(
            PropellantTab(
                a=float(tab.get("a", 0.0)),
                n=float(tab.get("n", 0.0)),
                k=float(tab.get("k", 0.0)),
                m=float(tab.get("m", 0.0)),
                t=float(tab.get("t", 0.0)),
                min_pressure_pa=float(tab.get("minPressure", 0.0)),
                max_pressure_pa=float(tab.get("maxPressure", 0.0)),
            )
        )
    if not tabs:
        raise ValueError("Missing propellant burn-rate tabs")
    return PropellantSpec(name=name, density_kg_m3=density, tabs=tabs)


def _parse_nozzle(nozzle: dict[str, Any]) -> NozzleSpec:
    return NozzleSpec(
        throat_diameter_m=float(nozzle.get("throat", 0.0)),
        exit_diameter_m=float(nozzle.get("exit", 0.0)),
        throat_length_m=float(nozzle.get("throatLength", 0.0)),
        conv_angle_deg=float(nozzle.get("convAngle", 0.0)),
        div_angle_deg=float(nozzle.get("divAngle", 0.0)),
        efficiency=float(nozzle.get("efficiency", 0.0)),
        erosion_coeff=float(nozzle.get("erosionCoeff", 0.0)),
        slag_coeff=float(nozzle.get("slagCoeff", 0.0)),
    )


def _parse_config(config: dict[str, Any]) -> MotorConfig:
    return MotorConfig(
        amb_pressure_pa=float(config.get("ambPressure", 0.0)),
        burnout_thrust_threshold_n=float(config.get("burnoutThrustThres", 0.0)),
        burnout_web_threshold_m=float(config.get("burnoutWebThres", 0.0)),
        map_dim=int(config.get("mapDim", 0)),
        max_mass_flux_kg_m2_s=float(config.get("maxMassFlux", 0.0)),
        max_pressure_pa=float(config.get("maxPressure", 0.0)),
        min_port_throat_ratio=float(config.get("minPortThroat", 0.0)),
        timestep_s=float(config.get("timestep", 0.0)),
    )


def spec_from_ric(ric: RicData) -> MotorSpec:
    return MotorSpec(
        config=_parse_config(ric.config),
        propellant=_parse_propellant(ric.propellant),
        grains=_require_bates(ric.grains),
        nozzle=_parse_nozzle(ric.nozzle),
    )
