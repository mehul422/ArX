from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.engine.openmotor_ai.motorlib_adapter import (
    metrics_from_simresult,
    simulate_motorlib_with_result,
)
from app.engine.openmotor_ai.spec import BATESGrain, MotorSpec, NozzleSpec, PropellantSpec

if TYPE_CHECKING:
    from app.engine.openmotor_ai.openmotor_pipeline import TwoStageConstraints, VehicleParams


@dataclass(frozen=True)
class SmartNozzleConfig:
    min_grains: int = 2
    max_grains: int = 15
    min_length_in: float = 2.0
    max_length_in: float = 24.0
    length_step_in: float = 0.5
    length_buffer_in: float = 1.0
    core_min_in: float = 0.5
    core_ratio_max: float = 0.65
    core_step_in: float = 0.125
    hardware_len_in: float = 4.0
    isp_estimate_s: float = 210.0
    c_star_in_s: float = 57600.0
    expansion_ratio: float = 8.0
    pressure_target_frac: float = 0.95
    throat_multipliers: tuple[float, ...] = (1.0, 1.2, 1.4, 1.6, 1.8, 2.0)
    max_winners: int = 6
    skip_apogee: bool = True


@dataclass(frozen=True)
class SmartNozzleResult:
    name: str
    spec: MotorSpec
    metrics: dict[str, float]
    apogee_ft: float | None
    max_velocity_m_s: float | None
    stage_length_in: float
    stage_diameter_in: float
    status: str
    reason: str | None = None


class ImpulseSizer:
    def __init__(self) -> None:
        self.g0 = 9.81
        self.rho_air = 1.225

    def calculate_targets(self, apogee_ft: float, mass_lbs: float, diam_in: float) -> float:
        target_m = apogee_ft * 0.3048
        dry_mass_kg = mass_lbs * 0.453592
        diameter_m = diam_in * 0.0254
        area = math.pi * (diameter_m / 2) ** 2

        low, high = 1000.0, 200000.0
        required_impulse = 0.0
        for _ in range(40):
            mid = (low + high) / 2.0
            prop_mass = mid / (self.g0 * 220.0)
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


class SmartNozzleArchitect:
    def __init__(self, config: SmartNozzleConfig | None = None) -> None:
        self.config = config or SmartNozzleConfig()
        self.sizer = ImpulseSizer()

    def _propellant_density_lb_in3(self, propellant: PropellantSpec) -> float:
        return propellant.density_kg_m3 * 0.0000361273

    def _propellant_tab(self, propellant: PropellantSpec) -> tuple[float, float]:
        tab = propellant.tabs[0]
        return tab.a, tab.n

    def _required_volume_in3(self, impulse_ns: float, propellant: PropellantSpec) -> float:
        impulse_lbfs = impulse_ns / 4.448
        req_prop_mass_lb = impulse_lbfs / max(self.config.isp_estimate_s, 1e-6)
        return req_prop_mass_lb / max(self._propellant_density_lb_in3(propellant), 1e-9)

    def _burn_area_in2(self, grains: int, length_in: float, core_in: float, od_in: float) -> float:
        core_area = math.pi * core_in * length_in
        face_area = 2.0 * (math.pi * (od_in**2 - core_in**2) / 4.0)
        total = (core_area + face_area) * grains
        return total * 1.10

    def _solve_nozzle(self, burn_area_in2: float, propellant: PropellantSpec, max_pressure_psi: float) -> tuple[float | None, float | None]:
        a, n = self._propellant_tab(propellant)
        rho = self._propellant_density_lb_in3(propellant)
        target_p = max_pressure_psi * self.config.pressure_target_frac
        try:
            numerator = target_p ** (1.0 - n)
            denominator = a * rho * self.config.c_star_in_s
            if denominator <= 0:
                return None, None
            max_kn = numerator / denominator
            if max_kn <= 0:
                return None, None
        except Exception:
            return None, None
        throat_area = burn_area_in2 / max_kn
        if throat_area <= 0:
            return None, None
        throat_d = math.sqrt((4.0 * throat_area) / math.pi)
        exit_area = throat_area * self.config.expansion_ratio
        exit_d = math.sqrt((4.0 * exit_area) / math.pi)
        return throat_d, exit_d

    def _build_spec(
        self,
        *,
        base_spec: MotorSpec,
        propellant: PropellantSpec,
        grain_count: int,
        grain_len_in: float,
        grain_od_in: float,
        core_in: float,
        throat_in: float,
        exit_in: float,
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
        nozzle = NozzleSpec(
            throat_diameter_m=throat_in * 0.0254,
            exit_diameter_m=exit_in * 0.0254,
            throat_length_m=base_spec.nozzle.throat_length_m,
            conv_angle_deg=base_spec.nozzle.conv_angle_deg,
            div_angle_deg=base_spec.nozzle.div_angle_deg,
            efficiency=base_spec.nozzle.efficiency,
            erosion_coeff=base_spec.nozzle.erosion_coeff,
            slag_coeff=base_spec.nozzle.slag_coeff,
        )
        return MotorSpec(
            config=base_spec.config,
            propellant=propellant,
            grains=grains,
            nozzle=nozzle,
        )

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
        progress_cb=None,
        progress_interval: int = 1,
        stage_length_target_in: float | None = None,
        stage_length_tolerance_in: float = 6.0,
        max_checks: int | None = None,
    ) -> list[SmartNozzleResult]:
        req_impulse = required_impulse_ns or self.sizer.calculate_targets(
            target_apogee_ft, dry_mass_lbs, rocket_dims["diameter"]
        )
        req_volume = self._required_volume_in3(req_impulse, propellant)

        winners: list[SmartNozzleResult] = []
        checked = 0
        closest_fail: SmartNozzleResult | None = None
        best_fail_score = 0.0

        grain_od = max(rocket_dims["diameter"] - 0.25, 0.5)
        core_max = grain_od * self.config.core_ratio_max

        for grain_count in range(self.config.min_grains, self.config.max_grains + 1):
            area_min = math.pi * ((grain_od / 2) ** 2 - (self.config.core_min_in / 2) ** 2)
            area_max = math.pi * ((grain_od / 2) ** 2 - (core_max / 2) ** 2)
            if area_min <= 0 or area_max <= 0:
                continue
            len_min = req_volume / (area_min * grain_count)
            len_max = req_volume / (area_max * grain_count)
            length_start = max(self.config.min_length_in, min(len_min, len_max) - self.config.length_buffer_in)
            length_end = min(self.config.max_length_in, max(len_min, len_max) + self.config.length_buffer_in)
            length = length_start
            while length <= length_end + 1e-6:
                total_len = grain_count * length + self.config.hardware_len_in
                if total_len > rocket_dims["max_length"]:
                    length += self.config.length_step_in
                    continue
                if stage_length_target_in is not None:
                    if abs(total_len - stage_length_target_in) > stage_length_tolerance_in:
                        length += self.config.length_step_in
                        continue
                core = self.config.core_min_in
                while core <= core_max + 1e-6:
                    burn_area = self._burn_area_in2(grain_count, length, core, grain_od)
                    pressure_limit = max_pressure_psi * 1.06
                    throat_base, exit_base = self._solve_nozzle(
                        burn_area, propellant, pressure_limit
                    )
                    if throat_base is None or exit_base is None:
                        core += self.config.core_step_in
                        continue
                    metrics = None
                    for multiplier in self.config.throat_multipliers:
                        throat_d = throat_base * multiplier
                        exit_d = exit_base * multiplier
                        checked += 1
                        if max_checks is not None and checked >= max_checks:
                            winners.sort(
                                key=lambda item: abs(
                                    item.metrics.get("total_impulse", 0.0) - req_impulse
                                )
                            )
                            return winners[: self.config.max_winners]
                        if progress_cb and checked % progress_interval == 0:
                            progress_cb(
                                {
                                    "checked": checked,
                                    "winners": len(winners),
                                    "propellant": propellant.name,
                                    "last_status": "attempt",
                                    "grain_count": grain_count,
                                    "grain_length_in": length,
                                    "grain_diameter_in": grain_od,
                                    "core_diameter_in": core,
                                    "throat_diameter_in": throat_d,
                                    "exit_diameter_in": exit_d,
                                    "stage_length_in": total_len,
                                }
                            )
                        try:
                            spec = self._build_spec(
                                base_spec=base_spec,
                                propellant=propellant,
                                grain_count=grain_count,
                                grain_len_in=length,
                                grain_od_in=grain_od,
                                core_in=core,
                                throat_in=throat_d,
                                exit_in=exit_d,
                            )
                            _, sim = simulate_motorlib_with_result(spec)
                            metrics = metrics_from_simresult(sim)
                        except Exception:
                            continue

                        peak_pressure = metrics.get("peak_chamber_pressure", 0.0) / 6894.757
                        total_impulse = metrics.get("total_impulse", 0.0)

                        if peak_pressure < pressure_limit * 1.5:
                            if total_impulse > best_fail_score:
                                best_fail_score = total_impulse
                                closest_fail = SmartNozzleResult(
                                    name=f"{propellant.name} {grain_count}x{length}\" core {core:.2f}\"",
                                    spec=spec,
                                    metrics=metrics,
                                    apogee_ft=None,
                                    max_velocity_m_s=None,
                                    stage_length_in=total_len,
                                    stage_diameter_in=grain_od,
                                    status="partial",
                                    reason="Pressure too high"
                                    if peak_pressure > max_pressure_psi
                                    else "Impulse too low",
                                )

                        if peak_pressure > pressure_limit:
                            continue
                        if total_impulse < req_impulse * 0.75:
                            continue

                        if self.config.skip_apogee:
                            apogee = None
                            apogee_ft = None
                        else:
                            try:
                                apogee = simulate_apogee(spec, metrics)
                                apogee_ft = apogee.apogee_m * 3.28084
                            except Exception:
                                continue

                            if apogee_ft < target_apogee_ft:
                                continue

                        winners.append(
                            SmartNozzleResult(
                                name=f"{propellant.name} {grain_count}x{length}\" core {core:.2f}\"",
                                spec=spec,
                                metrics=metrics,
                                apogee_ft=apogee_ft,
                                max_velocity_m_s=apogee.max_velocity_m_s if apogee else None,
                                stage_length_in=total_len,
                                stage_diameter_in=grain_od,
                                status="success",
                            )
                        )
                        if progress_cb:
                            progress_cb(
                                {
                                    "checked": checked,
                                    "winners": len(winners),
                                    "propellant": propellant.name,
                                    "last_status": "winner",
                                    "grain_count": grain_count,
                                    "grain_length_in": length,
                                    "grain_diameter_in": grain_od,
                                    "core_diameter_in": core,
                                    "throat_diameter_in": throat_d,
                                    "exit_diameter_in": exit_d,
                                    "stage_length_in": total_len,
                                }
                            )
                    if len(winners) >= self.config.max_winners:
                        winners.sort(
                            key=lambda item: abs(item.metrics.get("total_impulse", 0.0) - req_impulse)
                        )
                        return winners[: self.config.max_winners]
                    core += self.config.core_step_in
                length += self.config.length_step_in

        winners.sort(key=lambda item: abs(item.metrics.get("total_impulse", 0.0) - req_impulse))
        if winners:
            return winners[: self.config.max_winners]
        if closest_fail:
            return [closest_fail]
        return []
