from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.engine.openmotor_ai.motorlib_adapter import simulate_motorlib_with_result
from app.engine.openmotor_ai.spec import BATESGrain, MotorSpec, PropellantSpec

if TYPE_CHECKING:
    from app.engine.openmotor_ai.openmotor_pipeline import TwoStageConstraints, VehicleParams
    from app.engine.openmotor_ai.trajectory import (
        ApogeeResult,
    )


@dataclass(frozen=True)
class OptimizedSearchConfig:
    min_grains: int = 2
    max_grains: int = 15
    min_length_in: float = 2.0
    max_length_in: float = 24.0
    length_window_in: float = 1.0
    core_min_in: float = 0.5
    core_max_in: float = 2.5
    core_step_in: float = 0.25
    hardware_len_in: float = 4.0
    isp_estimate_s: float = 210.0


@dataclass(frozen=True)
class OptimizedResult:
    name: str
    spec: MotorSpec
    metrics: dict[str, float]
    apogee_ft: float
    max_velocity_m_s: float
    stage_length_in: float
    stage_diameter_in: float
    status: str
    reason: str | None = None


class ImpulseSizer:
    def __init__(self) -> None:
        self.g0 = 9.81
        self.rho_air = 1.225

    def calculate_required_impulse(
        self, target_alt_ft: float, dry_mass_lbs: float, diameter_in: float, isp: float = 220.0
    ) -> float:
        target_m = target_alt_ft * 0.3048
        dry_mass_kg = dry_mass_lbs * 0.453592
        diameter_m = diameter_in * 0.0254
        area = math.pi * (diameter_m / 2) ** 2

        low, high = 1000.0, 200000.0
        required_impulse = 0.0
        for _ in range(40):
            mid = (low + high) / 2.0
            prop_mass = mid / (isp * self.g0)
            avg_mass = dry_mass_kg + (prop_mass * 0.6)
            kinetic_energy = 0.5 * (mid**2 / max(avg_mass, 1e-6))
            drag_loss = 0.5 * self.rho_air * area * 0.75 * (target_m * 0.4)
            potential_energy = kinetic_energy - drag_loss
            est_h = potential_energy / max(avg_mass * self.g0, 1e-6)
            if est_h < target_m:
                low = mid
            else:
                high = mid
                required_impulse = mid
        return required_impulse


class OptimizedMotorArchitect:
    def __init__(self, config: OptimizedSearchConfig | None = None) -> None:
        self.config = config or OptimizedSearchConfig()
        self.sizer = ImpulseSizer()

    def _iter_core_diams(self) -> list[float]:
        step = self.config.core_step_in
        count = int(round((self.config.core_max_in - self.config.core_min_in) / step)) + 1
        return [self.config.core_min_in + i * step for i in range(count)]

    def _estimate_required_volume_in3(
        self, required_impulse_ns: float, propellant: PropellantSpec
    ) -> float:
        required_impulse_lbfs = required_impulse_ns / 4.448
        req_prop_mass_lb = required_impulse_lbfs / max(self.config.isp_estimate_s, 1e-6)
        density_lb_in3 = propellant.density_kg_m3 * 0.0000361273
        return req_prop_mass_lb / max(density_lb_in3, 1e-9)

    def _build_spec(
        self,
        *,
        base_spec: MotorSpec,
        propellant: PropellantSpec,
        grain_count: int,
        grain_len_in: float,
        grain_od_in: float,
        core_in: float,
    ) -> MotorSpec:
        grains = [
            BATESGrain(
                diameter_m=grain_od_in * 0.0254,
                core_diameter_m=core_in * 0.0254,
                length_m=grain_len_in * 0.0254,
                inhibited_ends="Neither",
            )
            for _ in range(grain_count)
        ]
        return MotorSpec(
            config=base_spec.config,
            propellant=propellant,
            grains=grains,
            nozzle=base_spec.nozzle,
        )

    def _simulate(self, spec: MotorSpec) -> tuple[list, dict[str, float]]:
        spec, steps, metrics, _ = simulate_motorlib_with_result(spec)
        return steps, metrics

    def find_optimal_motor(
        self,
        *,
        target_apogee_ft: float,
        dry_mass_lbs: float,
        max_pressure_psi: float,
        rocket_dims: dict[str, float],
        propellant: PropellantSpec,
        base_spec: MotorSpec,
        simulate_apogee,
        required_impulse_ns: float | None = None,
        stage_multiplier: int = 1,
    ) -> list[OptimizedResult]:
        req_impulse = required_impulse_ns or self.sizer.calculate_required_impulse(
            target_apogee_ft, dry_mass_lbs, rocket_dims["diameter"]
        )

        req_volume = self._estimate_required_volume_in3(req_impulse, propellant)

        candidates: list[tuple[int, float, float]] = []
        grain_od_in = max(rocket_dims["diameter"] - 0.25, 0.5)
        core_diams = self._iter_core_diams()

        for grain_count in range(self.config.min_grains, self.config.max_grains + 1):
            avg_core = grain_od_in * 0.35
            area_approx = math.pi * ((grain_od_in / 2) ** 2 - (avg_core / 2) ** 2)
            total_len_needed = req_volume / max(area_approx, 1e-9)
            len_per_grain = total_len_needed / grain_count
            base_len = round(len_per_grain * 2) / 2
            length_window = [
                base_len - self.config.length_window_in,
                base_len - (self.config.length_window_in / 2),
                base_len,
                base_len + (self.config.length_window_in / 2),
                base_len + self.config.length_window_in,
            ]
            for length in length_window:
                if length < self.config.min_length_in or length > self.config.max_length_in:
                    continue
                total_motor_len = (grain_count * length) + self.config.hardware_len_in
                if total_motor_len * stage_multiplier > rocket_dims["max_length"]:
                    continue
                for core in core_diams:
                    if core <= 0 or core >= grain_od_in:
                        continue
                    candidates.append((grain_count, length, core))

        winners: list[OptimizedResult] = []
        closest_fail: OptimizedResult | None = None
        best_fail_score = 0.0

        for count, length, core in candidates:
            try:
                spec = self._build_spec(
                    base_spec=base_spec,
                    propellant=propellant,
                    grain_count=count,
                    grain_len_in=length,
                    grain_od_in=grain_od_in,
                    core_in=core,
                )
                _, metrics = self._simulate(spec)
            except Exception:
                continue

            peak_pressure_psi = metrics.get("peak_chamber_pressure", 0.0) / 6894.757
            impulse_total = metrics.get("total_impulse", 0.0) * stage_multiplier
            total_len = (count * length + self.config.hardware_len_in) * stage_multiplier

            if peak_pressure_psi < max_pressure_psi * 1.5:
                if impulse_total > best_fail_score:
                    best_fail_score = impulse_total
                    closest_fail = OptimizedResult(
                        name=f"{propellant.name} {count}x{length}\" core {core}\"",
                        spec=spec,
                        metrics=metrics,
                        apogee_ft=0.0,
                        max_velocity_m_s=0.0,
                        stage_length_in=total_len,
                        stage_diameter_in=grain_od_in,
                        status="partial",
                        reason="Pressure too high"
                        if peak_pressure_psi > max_pressure_psi
                        else "Impulse too low",
                    )

            if peak_pressure_psi > max_pressure_psi:
                continue
            if impulse_total < req_impulse * 0.75:
                continue

            try:
                apogee = simulate_apogee(spec, metrics)
            except Exception:
                continue

            apogee_ft = apogee.apogee_m * 3.28084
            if apogee_ft < target_apogee_ft:
                continue

            winners.append(
                OptimizedResult(
                    name=f"{propellant.name} {count}x{length}\" core {core}\"",
                    spec=spec,
                    metrics=metrics,
                    apogee_ft=apogee_ft,
                    max_velocity_m_s=apogee.max_velocity_m_s,
                    stage_length_in=total_len,
                    stage_diameter_in=grain_od_in,
                    status="success",
                )
            )

        winners.sort(key=lambda item: abs(item.metrics.get("total_impulse", 0.0) - req_impulse))
        if winners:
            return winners[:5]
        if closest_fail:
            return [closest_fail]
        return []
