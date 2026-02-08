from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.engine.openmotor_ai.motorlib_adapter import simulate_motorlib_with_result
from app.engine.openmotor_ai.spec import BATESGrain, MotorSpec, PropellantSpec
from app.engine.openmotor_ai.trajectory import (
    simulate_single_stage_apogee_params,
    simulate_two_stage_apogee_params,
)

if TYPE_CHECKING:
    from app.engine.openmotor_ai.openmotor_pipeline import TwoStageConstraints, VehicleParams

@dataclass(frozen=True)
class GridSearchConfig:
    min_grains: int = 1
    max_grains: int = 12
    min_grain_len_in: float = 3.0
    max_grain_len_in: float = 24.0
    grain_len_step_in: float = 0.5
    min_core_in: float = 0.5
    max_core_in: float = 2.0
    core_step_in: float = 0.25
    hardware_len_in: float = 4.0
    max_winners: int = 40


@dataclass(frozen=True)
class GridResult:
    name: str
    spec: MotorSpec
    metrics: dict[str, float]
    apogee_ft: float
    max_velocity_m_s: float
    stage_length_in: float
    stage_diameter_in: float


class RocketDesignPipeline:
    def __init__(self, config: GridSearchConfig | None = None) -> None:
        self.config = config or GridSearchConfig()
        self.isp_guess_s = 220.0

    def _iter_grain_lengths(self) -> list[float]:
        step = self.config.grain_len_step_in
        count = int(round((self.config.max_grain_len_in - self.config.min_grain_len_in) / step)) + 1
        return [self.config.min_grain_len_in + i * step for i in range(count)]

    def _iter_core_diams(self) -> list[float]:
        step = self.config.core_step_in
        count = int(round((self.config.max_core_in - self.config.min_core_in) / step)) + 1
        return [self.config.min_core_in + i * step for i in range(count)]

    def _build_spec(
        self,
        *,
        propellant: PropellantSpec,
        base_spec: MotorSpec,
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

    def _simulate_motor(self, spec: MotorSpec) -> tuple[list, dict[str, float]]:
        spec, steps, metrics, _ = simulate_motorlib_with_result(spec)
        return steps, metrics

    def _estimate_impulse(
        self,
        *,
        grain_count: int,
        grain_len_in: float,
        grain_od_in: float,
        core_in: float,
        propellant: PropellantSpec,
    ) -> float:
        if grain_od_in <= 0 or core_in <= 0 or core_in >= grain_od_in:
            return 0.0
        area_in2 = math.pi * ((grain_od_in / 2) ** 2 - (core_in / 2) ** 2)
        volume_in3 = area_in2 * grain_len_in * grain_count
        density_lb_in3 = propellant.density_kg_m3 * 0.0000361273
        mass_lb = volume_in3 * density_lb_in3
        mass_kg = mass_lb * 0.453592
        return mass_kg * self.isp_guess_s * 9.81

    @staticmethod
    def _total_mass_from_dry(dry_mass_kg: float, metrics: dict[str, float]) -> float:
        prop = float(metrics.get("propellant_mass", 0.0) or 0.0)
        return max(dry_mass_kg + prop, 1e-6)

    @staticmethod
    def _split_stage_dry_masses(
        total_mass_kg: float, prop0: float, prop1: float
    ) -> tuple[float, float]:
        prop_total = max(prop0 + prop1, 1e-6)
        dry_total = max(total_mass_kg - prop_total, 0.0)
        ratio0 = prop0 / prop_total
        return dry_total * ratio0, dry_total * (1.0 - ratio0)

    def run_single_stage(
        self,
        *,
        propellant: PropellantSpec,
        base_spec: MotorSpec,
        target_impulse: float,
        target_apogee_ft: float,
        constraints: TwoStageConstraints,
        vehicle_params: VehicleParams,
        dry_mass_kg: float,
        cd_max: float,
        mach_max: float,
        cd_ramp: bool,
        launch_altitude_m: float,
        wind_speed_m_s: float,
        temperature_k: float | None,
        rod_length_m: float,
        launch_angle_deg: float,
        max_length_in: float,
    ) -> list[GridResult]:
        winners: list[GridResult] = []
        grain_od_in = max(vehicle_params.ref_diameter_m * 39.3701 - 0.25, 0.5)
        for grain_count in range(self.config.min_grains, self.config.max_grains + 1):
            for grain_len_in in self._iter_grain_lengths():
                for core_in in self._iter_core_diams():
                    if core_in >= grain_od_in:
                        continue
                    total_len = grain_count * grain_len_in + self.config.hardware_len_in
                    if total_len > max_length_in:
                        continue
                    est_impulse = self._estimate_impulse(
                        grain_count=grain_count,
                        grain_len_in=grain_len_in,
                        grain_od_in=grain_od_in,
                        core_in=core_in,
                        propellant=propellant,
                    )
                    if est_impulse < target_impulse * 0.9:
                        continue
                    try:
                        spec = self._build_spec(
                            propellant=propellant,
                            base_spec=base_spec,
                            grain_count=grain_count,
                            grain_len_in=grain_len_in,
                            grain_od_in=grain_od_in,
                            core_in=core_in,
                        )
                        _, metrics = self._simulate_motor(spec)
                    except Exception:
                        continue
                    peak_pressure_psi = metrics.get("peak_chamber_pressure", 0.0) / 6894.757
                    if peak_pressure_psi > constraints.max_pressure_psi:
                        continue
                    if metrics.get("total_impulse", 0.0) < target_impulse:
                        continue
                    total_mass_for_sim = self._total_mass_from_dry(dry_mass_kg, metrics)
                    try:
                        apogee = simulate_single_stage_apogee_params(
                            stage=spec,
                            ref_diameter_m=vehicle_params.ref_diameter_m,
                            total_mass_kg=total_mass_for_sim,
                            cd_max=cd_max,
                            mach_max=mach_max,
                            cd_ramp=cd_ramp,
                            launch_altitude_m=launch_altitude_m,
                            wind_speed_m_s=wind_speed_m_s,
                            temperature_k=temperature_k,
                            rod_length_m=rod_length_m,
                            launch_angle_deg=launch_angle_deg,
                        )
                    except Exception:
                        continue
                    apogee_ft = apogee.apogee_m * 3.28084
                    if apogee_ft < target_apogee_ft:
                        continue
                    winners.append(
                        GridResult(
                            name=f"{propellant.name} {grain_count}x{grain_len_in}\" core {core_in}\"",
                            spec=spec,
                            metrics=metrics,
                            apogee_ft=apogee_ft,
                            max_velocity_m_s=apogee.max_velocity_m_s,
                            stage_length_in=total_len,
                            stage_diameter_in=grain_od_in,
                        )
                    )
                    if len(winners) >= self.config.max_winners:
                        return winners
        return winners

    def run_two_stage_same_motor(
        self,
        *,
        propellant: PropellantSpec,
        base_spec: MotorSpec,
        target_impulse: float,
        target_apogee_ft: float,
        constraints: TwoStageConstraints,
        vehicle_params: VehicleParams,
        dry_mass_kg: float,
        cd_max: float,
        mach_max: float,
        cd_ramp: bool,
        launch_altitude_m: float,
        wind_speed_m_s: float,
        temperature_k: float | None,
        rod_length_m: float,
        launch_angle_deg: float,
        max_length_in: float,
    ) -> list[GridResult]:
        winners: list[GridResult] = []
        grain_od_in = max(vehicle_params.ref_diameter_m * 39.3701 - 0.25, 0.5)
        for grain_count in range(self.config.min_grains, self.config.max_grains + 1):
            for grain_len_in in self._iter_grain_lengths():
                for core_in in self._iter_core_diams():
                    if core_in >= grain_od_in:
                        continue
                    total_len = grain_count * grain_len_in + self.config.hardware_len_in
                    total_stack_len = total_len * 2
                    if total_stack_len > max_length_in:
                        continue
                    est_impulse = self._estimate_impulse(
                        grain_count=grain_count,
                        grain_len_in=grain_len_in,
                        grain_od_in=grain_od_in,
                        core_in=core_in,
                        propellant=propellant,
                    )
                    if est_impulse < (target_impulse / 2.0) * 0.9:
                        continue
                    try:
                        spec = self._build_spec(
                            propellant=propellant,
                            base_spec=base_spec,
                            grain_count=grain_count,
                            grain_len_in=grain_len_in,
                            grain_od_in=grain_od_in,
                            core_in=core_in,
                        )
                        _, metrics = self._simulate_motor(spec)
                    except Exception:
                        continue
                    peak_pressure_psi = metrics.get("peak_chamber_pressure", 0.0) / 6894.757
                    if peak_pressure_psi > constraints.max_pressure_psi:
                        continue
                    if metrics.get("total_impulse", 0.0) < target_impulse / 2.0:
                        continue
                    prop_mass = metrics.get("propellant_mass", 0.0)
                    total_mass_for_sim = max(dry_mass_kg + (prop_mass * 2.0), 1e-6)
                    stage0_dry, stage1_dry = self._split_stage_dry_masses(
                        total_mass_for_sim, prop_mass, prop_mass
                    )
                    try:
                        apogee = simulate_two_stage_apogee_params(
                            stage0=spec,
                            stage1=spec,
                            ref_diameter_m=vehicle_params.ref_diameter_m,
                            stage0_dry_kg=stage0_dry,
                            stage1_dry_kg=stage1_dry,
                            cd_max=cd_max,
                            mach_max=mach_max,
                            cd_ramp=cd_ramp,
                            separation_delay_s=0.0,
                            ignition_delay_s=0.0,
                            total_mass_kg=None,
                            launch_altitude_m=launch_altitude_m,
                            wind_speed_m_s=wind_speed_m_s,
                            temperature_k=temperature_k,
                            rod_length_m=rod_length_m,
                            launch_angle_deg=launch_angle_deg,
                        )
                    except Exception:
                        continue
                    apogee_ft = apogee.apogee_m * 3.28084
                    if apogee_ft < target_apogee_ft:
                        continue
                    winners.append(
                        GridResult(
                            name=f"{propellant.name} 2-stage {grain_count}x{grain_len_in}\" core {core_in}\"",
                            spec=spec,
                            metrics=metrics,
                            apogee_ft=apogee_ft,
                            max_velocity_m_s=apogee.max_velocity_m_s,
                            stage_length_in=total_stack_len,
                            stage_diameter_in=grain_od_in,
                        )
                    )
                    if len(winners) >= self.config.max_winners:
                        return winners
        return winners
