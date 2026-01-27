from __future__ import annotations

from typing import Any

import numpy as np


def _require_positive(value: float, name: str) -> float:
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def run_input_optimization(
    user_input: dict[str, Any], iterations: int = 25, population_size: int = 30
) -> dict[str, Any]:
    target_apogee_m = _require_positive(
        float(user_input.get("target_apogee_m", 0.0)), "target_apogee_m"
    )
    altitude_margin_m = float(user_input.get("altitude_margin_m", 0.0))
    max_mach = user_input.get("max_mach")
    if max_mach is not None:
        max_mach = _require_positive(float(max_mach), "max_mach")

    max_diameter_m = user_input.get("max_diameter_m")
    if max_diameter_m is not None:
        max_diameter_m = _require_positive(float(max_diameter_m), "max_diameter_m")

    payload_mass_kg = user_input.get("payload_mass_kg")
    if payload_mass_kg is not None:
        payload_mass_kg = _require_positive(float(payload_mass_kg), "payload_mass_kg")

    target_thrust_n = user_input.get("target_thrust_n")
    if target_thrust_n is not None:
        target_thrust_n = _require_positive(float(target_thrust_n), "target_thrust_n")

    constraints = user_input.get("constraints", {})
    max_total_mass_kg = constraints.get("max_total_mass_kg")
    if max_total_mass_kg is not None:
        max_total_mass_kg = _require_positive(float(max_total_mass_kg), "max_total_mass_kg")

    base_thrust_n = target_thrust_n or max(1000.0, target_apogee_m * 8.0)
    base_payload_kg = payload_mass_kg or max(5.0, (max_total_mass_kg or 50.0) * 0.15)

    best = None
    best_score = float("-inf")
    history: list[dict[str, Any]] = []

    low, high = 0.8, 1.2
    for iteration in range(iterations):
        scales = np.linspace(low, high, population_size)
        iteration_best = None
        iteration_best_score = float("-inf")
        for scale in scales:
            thrust_n = base_thrust_n * float(scale)
            estimated_apogee_m = thrust_n * 0.1
            estimated_max_mach = min(3.0, 0.2 + thrust_n / 20000.0)
            score = -abs(estimated_apogee_m - target_apogee_m)
            if max_mach is not None and estimated_max_mach > max_mach:
                score -= (estimated_max_mach - max_mach) * 1000.0

            if score > iteration_best_score:
                iteration_best_score = score
                iteration_best = {
                    "scale": float(scale),
                    "score": float(score),
                    "estimated_apogee_m": float(estimated_apogee_m),
                    "estimated_max_mach": float(estimated_max_mach),
                    "estimated_thrust_n": float(thrust_n),
                }
        if iteration_best:
            history.append({"iteration": iteration + 1, **iteration_best})
            if iteration_best_score > best_score:
                best_score = iteration_best_score
                best = iteration_best
            span = max(0.05, (high - low) * 0.5)
            low = max(0.5, iteration_best["scale"] - span / 2.0)
            high = min(2.0, iteration_best["scale"] + span / 2.0)

    best = best or {
        "scale": 1.0,
        "score": float("-inf"),
        "estimated_apogee_m": base_thrust_n * 0.1,
        "estimated_max_mach": min(3.0, 0.2 + base_thrust_n / 20000.0),
        "estimated_thrust_n": base_thrust_n,
    }

    estimated_total_mass_kg = max(base_payload_kg * 4.0, base_payload_kg + 10.0)
    if max_total_mass_kg is not None:
        estimated_total_mass_kg = min(estimated_total_mass_kg, max_total_mass_kg)

    recommended = {
        "target_apogee_m": target_apogee_m,
        "altitude_margin_m": altitude_margin_m,
        "max_mach": max_mach,
        "max_diameter_m": max_diameter_m,
        "payload_mass_kg": base_payload_kg,
        "target_thrust_n": best["estimated_thrust_n"],
        "constraints": {"max_total_mass_kg": max_total_mass_kg},
    }

    return {
        "recommended": recommended,
        "summary": {
            "estimated_apogee_m": best["estimated_apogee_m"],
            "estimated_max_mach": best["estimated_max_mach"],
            "estimated_total_mass_kg": estimated_total_mass_kg,
            "best_scale": best["scale"],
            "score": best["score"],
        },
        "iterations": history,
    }
