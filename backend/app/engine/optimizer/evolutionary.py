from typing import Any

import numpy as np


def run_evolutionary_optimization(params: dict[str, Any]) -> dict[str, Any]:
    population_size = int(params.get("population_size", 30))
    iterations = int(params.get("iterations", 25))
    bounds = params.get("bounds", {"min": 0.0, "max": 1.0})

    lower = float(bounds.get("min", 0.0))
    upper = float(bounds.get("max", 1.0))
    if population_size <= 0 or iterations <= 0:
        raise ValueError("population_size and iterations must be positive")
    if lower >= upper:
        raise ValueError("bounds.min must be less than bounds.max")

    rng = np.random.default_rng()
    best_candidate = None
    best_score = float("-inf")

    for _ in range(iterations):
        population = rng.uniform(lower, upper, population_size)
        scores = -np.square(population - (lower + upper) / 2.0)
        best_idx = int(np.argmax(scores))
        if scores[best_idx] > best_score:
            best_score = float(scores[best_idx])
            best_candidate = float(population[best_idx])

    return {
        "best_candidate": best_candidate,
        "best_score": best_score,
        "population_size": population_size,
        "iterations": iterations,
        "bounds": {"min": lower, "max": upper},
    }
