from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.engine.openmotor_ai.ballistics import aggregate_metrics, simulate_ballistics
from app.engine.openmotor_ai.eng_parser import EngData
from app.engine.openmotor_ai.metrics import BasicMetrics, compute_basic_metrics, metric_skeleton
from app.engine.openmotor_ai.ric_parser import RicData
from app.engine.openmotor_ai.spec import MotorSpec, spec_from_ric


@dataclass(frozen=True)
class SimulationResult:
    spec: MotorSpec
    metrics: dict[str, float | None]
    basic: BasicMetrics


def simulate_from_reference(ric: RicData, eng: EngData) -> SimulationResult:
    """
    Clean-room placeholder: compute metrics that are strictly derived from the
    .ric spec and the provided .eng thrust curve. This provides a deterministic
    baseline for regression tests while the full solver is implemented.
    """
    spec = spec_from_ric(ric)
    basic = compute_basic_metrics(ric, eng)
    metrics = metric_skeleton()
    metrics["burn_time"] = basic.burn_time_s
    metrics["total_impulse"] = basic.total_impulse_ns
    metrics["propellant_mass"] = basic.propellant_mass_kg
    metrics["propellant_length"] = basic.propellant_length_m
    return SimulationResult(spec=spec, metrics=metrics, basic=basic)


def simulate_physics(spec: MotorSpec) -> dict[str, float]:
    steps = simulate_ballistics(spec)
    return aggregate_metrics(spec, steps)
