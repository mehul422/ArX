from __future__ import annotations

from pathlib import Path
import sys
from typing import Iterable, Tuple

from app.engine.openmotor_ai.spec import MotorSpec


def _ensure_motorlib() -> None:
    root = Path(__file__).resolve().parents[3]
    vendor_path = root / "third_party" / "openmotor_src"
    if not vendor_path.exists():
        raise FileNotFoundError(f"OpenMotor sources not found: {vendor_path}")
    path_str = str(vendor_path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def _motor_dict(spec: MotorSpec) -> dict:
    return {
        "nozzle": {
            "throat": spec.nozzle.throat_diameter_m,
            "exit": spec.nozzle.exit_diameter_m,
            "efficiency": spec.nozzle.efficiency,
            "divAngle": spec.nozzle.div_angle_deg,
            "convAngle": spec.nozzle.conv_angle_deg,
            "throatLength": spec.nozzle.throat_length_m,
            "slagCoeff": spec.nozzle.slag_coeff,
            "erosionCoeff": spec.nozzle.erosion_coeff,
        },
        "propellant": {
            "name": spec.propellant.name,
            "density": spec.propellant.density_kg_m3,
            "tabs": [
                {
                    "minPressure": tab.min_pressure_pa,
                    "maxPressure": tab.max_pressure_pa,
                    "a": tab.a,
                    "n": tab.n,
                    "k": tab.k,
                    "t": tab.t,
                    "m": tab.m,
                }
                for tab in spec.propellant.tabs
            ],
        },
        "grains": [
            {
                "type": "BATES",
                "properties": {
                    "diameter": grain.diameter_m,
                    "coreDiameter": grain.core_diameter_m,
                    "length": grain.length_m,
                    "inhibitedEnds": grain.inhibited_ends,
                },
            }
            for grain in spec.grains
        ],
        "config": {
            "ambPressure": spec.config.amb_pressure_pa,
            "burnoutThrustThres": spec.config.burnout_thrust_threshold_n,
            "burnoutWebThres": spec.config.burnout_web_threshold_m,
            "mapDim": spec.config.map_dim,
            "maxMassFlux": spec.config.max_mass_flux_kg_m2_s,
            "maxPressure": spec.config.max_pressure_pa,
            "minPortThroat": spec.config.min_port_throat_ratio,
            "timestep": spec.config.timestep_s,
        },
    }


def _safe_last(values: Iterable[float]) -> float:
    items = list(values)
    return items[-1] if items else 0.0


def _float_or(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_or(value: object, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _motor_dict_from_ric_data(ric: "RicData") -> dict:
    nozzle = ric.nozzle or {}
    propellant = ric.propellant or {}
    config = ric.config or {}
    grains = ric.grains or []
    return {
        "nozzle": {
            "throat": _float_or(nozzle.get("throat")),
            "exit": _float_or(nozzle.get("exit")),
            "efficiency": _float_or(nozzle.get("efficiency")),
            "divAngle": _float_or(nozzle.get("divAngle")),
            "convAngle": _float_or(nozzle.get("convAngle")),
            "throatLength": _float_or(nozzle.get("throatLength")),
            "slagCoeff": _float_or(nozzle.get("slagCoeff")),
            "erosionCoeff": _float_or(nozzle.get("erosionCoeff")),
        },
        "propellant": {
            "name": propellant.get("name", ""),
            "density": _float_or(propellant.get("density")),
            "tabs": [
                {
                    "minPressure": _float_or(tab.get("minPressure")),
                    "maxPressure": _float_or(tab.get("maxPressure")),
                    "a": _float_or(tab.get("a")),
                    "n": _float_or(tab.get("n")),
                    "k": _float_or(tab.get("k")),
                    "t": _float_or(tab.get("t")),
                    "m": _float_or(tab.get("m")),
                }
                for tab in (propellant.get("tabs") or [])
                if isinstance(tab, dict)
            ],
        },
        "grains": [
            {
                "type": grain.get("type", "BATES"),
                "properties": {
                    "diameter": _float_or((grain.get("properties") or {}).get("diameter")),
                    "coreDiameter": _float_or((grain.get("properties") or {}).get("coreDiameter")),
                    "length": _float_or((grain.get("properties") or {}).get("length")),
                    "inhibitedEnds": _int_or((grain.get("properties") or {}).get("inhibitedEnds")),
                },
            }
            for grain in grains
            if isinstance(grain, dict)
        ],
        "config": {
            "ambPressure": _float_or(config.get("ambPressure")),
            "burnoutThrustThres": _float_or(config.get("burnoutThrustThres")),
            "burnoutWebThres": _float_or(config.get("burnoutWebThres")),
            "mapDim": _int_or(config.get("mapDim")),
            "maxMassFlux": _float_or(config.get("maxMassFlux")),
            "maxPressure": _float_or(config.get("maxPressure")),
            "minPortThroat": _float_or(config.get("minPortThroat")),
            "timestep": _float_or(config.get("timestep")),
        },
    }


def simulate_motorlib_with_result(spec: MotorSpec) -> Tuple[list["TimeStep"], "SimulationResult"]:
    _ensure_motorlib()
    from motorlib.motor import Motor
    from motorlib.simResult import SimAlertLevel
    from motorlib.simResult import SimulationResult

    from app.engine.openmotor_ai.ballistics import TimeStep

    motor = Motor(_motor_dict(spec))
    sim: SimulationResult = motor.runSimulation()
    if sim.getAlertsByLevel(SimAlertLevel.ERROR):
        messages = [alert.description for alert in sim.getAlertsByLevel(SimAlertLevel.ERROR)]
        raise RuntimeError(f"OpenMotor simulation errors: {messages}")

    steps: list[TimeStep] = []
    times = sim.channels["time"].getData()
    for idx, time_s in enumerate(times):
        pressure = sim.channels["pressure"].getPoint(idx)
        thrust = sim.channels["force"].getPoint(idx)
        kn = sim.channels["kn"].getPoint(idx)
        mass_flow = _safe_last(sim.channels["massFlow"].getPoint(idx))
        reg_depth = _safe_last(sim.channels["regression"].getPoint(idx))
        port_area = motor.grains[-1].getPortArea(reg_depth) or 0.0
        steps.append(
            TimeStep(
                time_s=time_s,
                chamber_pressure_pa=pressure,
                thrust_n=thrust,
                mass_flow_kg_s=mass_flow,
                kn=kn,
                port_area_m2=port_area,
            )
        )
    return steps, sim


def simulate_motorlib_with_result_from_ric(
    ric_path: str,
) -> Tuple[list["TimeStep"], "SimulationResult"]:
    _ensure_motorlib()
    from motorlib.motor import Motor
    from motorlib.simResult import SimAlertLevel
    from motorlib.simResult import SimulationResult

    from app.engine.openmotor_ai.ballistics import TimeStep
    from app.engine.openmotor_ai.ric_parser import load_ric

    ric = load_ric(ric_path)
    motor = Motor(_motor_dict_from_ric_data(ric))
    sim: SimulationResult = motor.runSimulation()
    if sim.getAlertsByLevel(SimAlertLevel.ERROR):
        messages = [alert.description for alert in sim.getAlertsByLevel(SimAlertLevel.ERROR)]
        raise RuntimeError(f"OpenMotor simulation errors: {messages}")

    steps: list[TimeStep] = []
    times = sim.channels["time"].getData()
    for idx, time_s in enumerate(times):
        pressure = sim.channels["pressure"].getPoint(idx)
        thrust = sim.channels["force"].getPoint(idx)
        kn = sim.channels["kn"].getPoint(idx)
        mass_flow = _safe_last(sim.channels["massFlow"].getPoint(idx))
        reg_depth = _safe_last(sim.channels["regression"].getPoint(idx))
        port_area = motor.grains[-1].getPortArea(reg_depth) or 0.0
        steps.append(
            TimeStep(
                time_s=time_s,
                chamber_pressure_pa=pressure,
                thrust_n=thrust,
                mass_flow_kg_s=mass_flow,
                kn=kn,
                port_area_m2=port_area,
            )
        )
    return steps, sim


def simulate_motorlib_from_ric(ric_path: str) -> list["TimeStep"]:
    steps, _ = simulate_motorlib_with_result_from_ric(ric_path)
    return steps


def simulate_motorlib(spec: MotorSpec) -> list["TimeStep"]:
    steps, _ = simulate_motorlib_with_result(spec)
    return steps


def metrics_from_simresult(sim: "SimulationResult") -> dict[str, float]:
    return {
        "burn_time": float(sim.getBurnTime()),
        "total_impulse": float(sim.getImpulse()),
        "average_thrust": float(sim.getAverageForce()),
        "average_chamber_pressure": float(sim.getAveragePressure()),
        "peak_chamber_pressure": float(sim.getMaxPressure()),
        "initial_kn": float(sim.getInitialKN()),
        "peak_kn": float(sim.getPeakKN()),
        "ideal_thrust_coefficient": float(sim.getIdealThrustCoefficient()),
        "delivered_thrust_coefficient": float(sim.getAdjustedThrustCoefficient()),
        "delivered_specific_impulse": float(sim.getISP()),
        "propellant_mass": float(sim.getPropellantMass()),
        "propellant_length": float(sim.getPropellantLength()),
        "port_to_throat_ratio": float(sim.getPortRatio() or 0.0),
        "volume_loading": float(sim.getVolumeLoading()),
        "peak_mass_flux": float(sim.getPeakMassFlux()),
    }
