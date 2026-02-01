from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable


@dataclass(frozen=True)
class ScoreWeights:
    apogee: float = 0.30
    efficiency: float = 0.20
    thrust_quality: float = 0.15
    pressure_margin: float = 0.10
    kn_margin: float = 0.10
    packaging: float = 0.10
    manufacturability: float = 0.05


@dataclass(frozen=True)
class Candidate:
    name: str
    metrics: dict[str, float]
    thrust_curve: list[tuple[float, float]] | None = None
    apogee_ft: float | None = None
    vehicle_length_in: float | None = None
    stage_length_in: float | None = None
    stage_diameter_in: float | None = None


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: Candidate
    objective_scores: dict[str, float]
    total_score: float
    classification: list[str]
    explanation: str


def _normalize(values: list[float]) -> list[float]:
    if not values:
        return []
    vmin = min(values)
    vmax = max(values)
    if vmax - vmin <= 1e-9:
        return [1.0 for _ in values]
    return [(v - vmin) / (vmax - vmin) for v in values]


def _thrust_quality_score(curve: list[tuple[float, float]] | None) -> float:
    if not curve or len(curve) < 3:
        return 0.5
    dts = []
    for i in range(1, len(curve)):
        dt = curve[i][0] - curve[i - 1][0]
        if dt > 0:
            dts.append((curve[i][1] - curve[i - 1][1]) / dt)
    if not dts:
        return 0.5
    max_spike = max(abs(v) for v in dts)
    return 1.0 / (1.0 + (max_spike / 10000.0))


def _pressure_margin(peak_pressure: float, p_max: float) -> float:
    return max((p_max - peak_pressure) / max(p_max, 1e-6), 0.0)


def _kn_margin(peak_kn: float, kn_max: float) -> float:
    return max((kn_max - peak_kn) / max(kn_max, 1e-6), 0.0)


def _packaging_score(stage_len: float | None, vehicle_len: float | None) -> float:
    if stage_len is None or vehicle_len is None or vehicle_len <= 0:
        return 0.5
    return max(1.0 - (stage_len / vehicle_len), 0.0)


def _manufacturability_score(metrics: dict[str, float]) -> float:
    score = 1.0
    port_throat = metrics.get("port_to_throat_ratio", 0.0)
    peak_mass_flux = metrics.get("peak_mass_flux", 0.0)
    if port_throat < 1.0:
        score *= 0.7
    if port_throat > 4.0:
        score *= 0.8
    if peak_mass_flux > 2000:
        score *= 0.7
    return max(min(score, 1.0), 0.0)


def classify_candidate(metrics: dict[str, float]) -> list[str]:
    labels = []
    burn_time = metrics.get("burn_time", 0.0)
    avg_thrust = metrics.get("average_thrust", 0.0)
    peak_pressure = metrics.get("peak_chamber_pressure", 0.0)
    peak_kn = metrics.get("peak_kn", 0.0)

    if burn_time < 3.0 and avg_thrust > 4000:
        labels.append("High-thrust booster")
    if burn_time > 6.0 and avg_thrust < 5000:
        labels.append("Sustainer")
    if metrics.get("delivered_specific_impulse", 0.0) > 160:
        labels.append("High-efficiency sustainer")
    if peak_pressure > 0.9 * metrics.get("max_pressure", peak_pressure + 1.0):
        labels.append("Pressure-limited design")
    if peak_kn > 0.9 * metrics.get("max_kn", peak_kn + 1.0):
        labels.append("Kn-limited design")
    return labels


def score_candidates(
    candidates: list[Candidate],
    p_max: float,
    kn_max: float,
    weights: ScoreWeights | None = None,
) -> list[ScoredCandidate]:
    if weights is None:
        weights = ScoreWeights()

    apogee_vals = [c.apogee_ft or 0.0 for c in candidates]
    isp_vals = [c.metrics.get("delivered_specific_impulse", 0.0) for c in candidates]
    pressure_vals = [c.metrics.get("peak_chamber_pressure", 0.0) for c in candidates]
    kn_vals = [c.metrics.get("peak_kn", 0.0) for c in candidates]
    packaging_vals = [
        _packaging_score(c.stage_length_in, c.vehicle_length_in) for c in candidates
    ]
    thrust_quality_vals = [_thrust_quality_score(c.thrust_curve) for c in candidates]
    manuf_vals = [_manufacturability_score(c.metrics) for c in candidates]

    apogee_norm = _normalize(apogee_vals)
    isp_norm = _normalize(isp_vals)
    pressure_norm = _normalize([_pressure_margin(v, p_max) for v in pressure_vals])
    kn_norm = _normalize([_kn_margin(v, kn_max) for v in kn_vals])
    packaging_norm = _normalize(packaging_vals)
    thrust_norm = _normalize(thrust_quality_vals)
    manuf_norm = _normalize(manuf_vals)

    scored: list[ScoredCandidate] = []
    for idx, candidate in enumerate(candidates):
        objective_scores = {
            "apogee": apogee_norm[idx],
            "efficiency": isp_norm[idx],
            "thrust_quality": thrust_norm[idx],
            "pressure_margin": pressure_norm[idx],
            "kn_margin": kn_norm[idx],
            "packaging": packaging_norm[idx],
            "manufacturability": manuf_norm[idx],
        }
        total = (
            objective_scores["apogee"] * weights.apogee
            + objective_scores["efficiency"] * weights.efficiency
            + objective_scores["thrust_quality"] * weights.thrust_quality
            + objective_scores["pressure_margin"] * weights.pressure_margin
            + objective_scores["kn_margin"] * weights.kn_margin
            + objective_scores["packaging"] * weights.packaging
            + objective_scores["manufacturability"] * weights.manufacturability
        )
        labels = classify_candidate(candidate.metrics)
        explanation = (
            f"apogee={objective_scores['apogee']:.2f}, isp={objective_scores['efficiency']:.2f}, "
            f"pressure_margin={objective_scores['pressure_margin']:.2f}, kn_margin={objective_scores['kn_margin']:.2f}"
        )
        scored.append(
            ScoredCandidate(
                candidate=candidate,
                objective_scores=objective_scores,
                total_score=total,
                classification=labels,
                explanation=explanation,
            )
        )

    scored.sort(key=lambda s: s.total_score, reverse=True)
    return scored
