from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from app.api.v1.units import in_to_m, lb_to_kg
from app.engine.openmotor_ai.motorlib_adapter import metrics_from_simresult, simulate_motorlib_with_result
from app.engine.openmotor_ai.ric_parser import load_ric
from app.engine.openmotor_ai.spec import (
    BATESGrain,
    MotorConfig,
    MotorSpec,
    NozzleSpec,
    PropellantSpec,
    PropellantTab,
)
from app.engine.openmotor_ai.trajectory import simulate_single_stage_apogee_params


def _objective_error_pct_max(
    apogee_ft: float | None,
    max_velocity_m_s: float | None,
    target_apogee_ft: float | None,
    target_max_velocity_m_s: float | None,
) -> float | None:
    errors: list[float] = []
    if target_apogee_ft is not None and apogee_ft is not None:
        if apogee_ft <= target_apogee_ft:
            errors.append((target_apogee_ft - apogee_ft) / max(target_apogee_ft, 1e-6))
        else:
            errors.append(1.0 + (apogee_ft - target_apogee_ft) / max(target_apogee_ft, 1e-6))
    if target_max_velocity_m_s is not None and max_velocity_m_s is not None:
        if max_velocity_m_s <= target_max_velocity_m_s:
            errors.append(
                (target_max_velocity_m_s - max_velocity_m_s)
                / max(target_max_velocity_m_s, 1e-6)
            )
        else:
            errors.append(
                1.0 + (max_velocity_m_s - target_max_velocity_m_s) / max(target_max_velocity_m_s, 1e-6)
            )
    if not errors:
        return None
    return float(sum(errors) / len(errors))


def _within_max_targets(
    apogee_ft: float | None,
    max_velocity_m_s: float | None,
    target_apogee_ft: float | None,
    target_max_velocity_m_s: float | None,
) -> bool:
    if target_apogee_ft is not None and apogee_ft is not None and apogee_ft > target_apogee_ft:
        return False
    if (
        target_max_velocity_m_s is not None
        and max_velocity_m_s is not None
        and max_velocity_m_s > target_max_velocity_m_s
    ):
        return False
    return True


def _propellant_from_payload(payload: dict) -> PropellantSpec:
    tabs = [
        PropellantTab(
            a=float(tab.get("a", 0.0)),
            n=float(tab.get("n", 0.0)),
            k=float(tab.get("k", 0.0)),
            m=float(tab.get("m", 0.0)),
            t=float(tab.get("t", 0.0)),
            min_pressure_pa=float(tab.get("minPressure", 0.0)),
            max_pressure_pa=float(tab.get("maxPressure", 0.0)),
        )
        for tab in (payload.get("tabs") or [])
    ]
    if not tabs:
        raise ValueError("motor_spec.propellant.tabs required")
    return PropellantSpec(
        name=str(payload.get("name", "")),
        density_kg_m3=float(payload.get("density", 0.0)),
        tabs=tabs,
    )


def _grains_from_payload(payload: list[dict]) -> list[BATESGrain]:
    grains = []
    for item in payload:
        if item.get("type") != "BATES":
            raise ValueError("Only BATES grains supported for motor_spec")
        props = item.get("properties", {})
        grains.append(
            BATESGrain(
                diameter_m=float(props.get("diameter", 0.0)),
                core_diameter_m=float(props.get("coreDiameter", 0.0)),
                length_m=float(props.get("length", 0.0)),
                inhibited_ends=str(props.get("inhibitedEnds", "")),
            )
        )
    if not grains:
        raise ValueError("motor_spec.grains required")
    return grains


def _nozzle_from_payload(payload: dict) -> NozzleSpec:
    return NozzleSpec(
        throat_diameter_m=float(payload.get("throat", 0.0)),
        exit_diameter_m=float(payload.get("exit", 0.0)),
        throat_length_m=float(payload.get("throatLength", 0.0)),
        conv_angle_deg=float(payload.get("convAngle", 0.0)),
        div_angle_deg=float(payload.get("divAngle", 0.0)),
        efficiency=float(payload.get("efficiency", 1.0)),
        erosion_coeff=float(payload.get("erosionCoeff", 0.0)),
        slag_coeff=float(payload.get("slagCoeff", 0.0)),
    )


def _config_from_payload(payload: dict) -> MotorConfig:
    return MotorConfig(
        amb_pressure_pa=float(payload.get("ambPressure", 101325.0)),
        burnout_thrust_threshold_n=float(payload.get("burnoutThrustThres", 0.1)),
        burnout_web_threshold_m=float(payload.get("burnoutWebThres", 2.54e-5)),
        map_dim=int(payload.get("mapDim", 750)),
        max_mass_flux_kg_m2_s=float(payload.get("maxMassFlux", 1400.0)),
        max_pressure_pa=float(payload.get("maxPressure", 1.2e7)),
        min_port_throat_ratio=float(payload.get("minPortThroat", 2.0)),
        timestep_s=float(payload.get("timestep", 0.03)),
    )


def _motor_spec_from_payload(payload: dict) -> MotorSpec:
    return MotorSpec(
        propellant=_propellant_from_payload(payload.get("propellant") or {}),
        grains=_grains_from_payload(payload.get("grains") or []),
        nozzle=_nozzle_from_payload(payload.get("nozzle") or {}),
        config=_config_from_payload(payload.get("config") or {}),
    )


def _rocket_defaults(spec: MotorSpec) -> dict[str, float]:
    diameter_m = max(grain.diameter_m for grain in spec.grains)
    length_m = sum(grain.length_m for grain in spec.grains)
    return {
        "motor_diameter_in": diameter_m * 39.3701,
        "motor_length_in": length_m * 39.3701,
    }


def _default_design_space() -> dict[str, list[float]]:
    return {
        "diameter_scales": [1.0, 1.1, 1.2],
        "length_scales": [1.2, 1.4, 1.6],
        "mass_scales": [1.5, 2.0, 2.5],
    }


def _ai_seed_overrides(ai_prompt: str | None) -> dict[str, float]:
    if not ai_prompt:
        return {}
    text = ai_prompt.lower()
    overrides = {}
    if "lightweight" in text or "min mass" in text:
        overrides["mass_scale"] = 0.9
    if "aggressive" in text or "high altitude" in text:
        overrides["length_scale"] = 1.2
    if "compact" in text:
        overrides["length_scale"] = 0.9
    return overrides


def run_motor_first_design(
    *,
    motor_ric_path: str | None,
    motor_spec_payload: dict | None,
    objectives: dict[str, float | None],
    constraints: dict[str, float],
    design_space: dict[str, list[float]] | None,
    output_dir: str,
    cd_max: float,
    mach_max: float,
    cd_ramp: bool,
    tolerance_pct: float,
    ai_prompt: str | None,
) -> dict[str, object]:
    if motor_ric_path:
        ric = load_ric(motor_ric_path)
        from app.engine.openmotor_ai.spec import spec_from_ric

        spec = spec_from_ric(ric)
    elif motor_spec_payload:
        spec = _motor_spec_from_payload(motor_spec_payload)
    else:
        raise ValueError("motor_ric_path or motor_spec required")

    motor_metrics = None
    _, sim = simulate_motorlib_with_result(spec)
    motor_metrics = metrics_from_simresult(sim)
    peak_pressure_psi = motor_metrics.get("peak_chamber_pressure", 0.0) / 6894.757
    peak_kn = motor_metrics.get("peak_kn", 0.0)

    max_pressure_psi = constraints.get("max_pressure_psi")
    max_kn = constraints.get("max_kn")
    if max_pressure_psi and peak_pressure_psi > max_pressure_psi:
        return {
            "summary": {"status": "motor_outside_constraints", "message": "peak pressure exceeds limit"},
            "motor_metrics": motor_metrics,
            "candidates": [],
            "ranked": [],
        }
    if max_kn and peak_kn > max_kn:
        return {
            "summary": {"status": "motor_outside_constraints", "message": "peak kn exceeds limit"},
            "motor_metrics": motor_metrics,
            "candidates": [],
            "ranked": [],
        }

    defaults = _rocket_defaults(spec)
    base_diameter_in = min(defaults["motor_diameter_in"] * 1.1, constraints["max_vehicle_diameter_in"])
    base_length_in = min(defaults["motor_length_in"] * 1.5, constraints["max_vehicle_length_in"])
    prop_mass_lb = motor_metrics.get("propellant_mass", 0.0) * 2.20462
    base_mass_lb = min(max(prop_mass_lb * 2.5, prop_mass_lb + 10.0), constraints["max_total_mass_lb"])

    space = _default_design_space()
    if design_space:
        space.update({k: v for k, v in design_space.items() if v})

    ai_overrides = _ai_seed_overrides(ai_prompt)
    if "mass_scale" in ai_overrides:
        base_mass_lb = min(base_mass_lb * ai_overrides["mass_scale"], constraints["max_total_mass_lb"])
    if "length_scale" in ai_overrides:
        base_length_in = min(
            base_length_in * ai_overrides["length_scale"], constraints["max_vehicle_length_in"]
        )

    target_apogee_ft = objectives.get("apogee_ft")
    target_max_velocity_m_s = objectives.get("max_velocity_m_s")

    def evaluate_candidate(diameter_in: float, length_in: float, total_mass_lb: float) -> dict[str, object]:
        total_mass_kg = lb_to_kg(total_mass_lb)
        apogee = simulate_single_stage_apogee_params(
            stage=spec,
            ref_diameter_m=in_to_m(diameter_in),
            total_mass_kg=total_mass_kg,
            cd_max=cd_max,
            mach_max=mach_max,
            cd_ramp=cd_ramp,
        )
        apogee_ft = apogee.apogee_m * 3.28084
        error = _objective_error_pct_max(
            apogee_ft, apogee.max_velocity_m_s, target_apogee_ft, target_max_velocity_m_s
        )
        within_tolerance = bool(
            error is not None
            and error <= tolerance_pct
            and _within_max_targets(
                apogee_ft, apogee.max_velocity_m_s, target_apogee_ft, target_max_velocity_m_s
            )
        )
        rocket = {
            "diameter_in": diameter_in,
            "length_in": length_in,
            "total_mass_lb": total_mass_lb,
        }
        return {
            "rocket": rocket,
            "apogee_ft": apogee_ft,
            "max_velocity_m_s": apogee.max_velocity_m_s,
            "max_accel_m_s2": apogee.max_accel_m_s2,
            "objective_error_pct": (error * 100.0) if error is not None else None,
            "within_tolerance": within_tolerance,
        }

    candidates: list[dict[str, object]] = []
    for d_scale in space["diameter_scales"]:
        for l_scale in space["length_scales"]:
            for m_scale in space["mass_scales"]:
                diameter_in = min(base_diameter_in * d_scale, constraints["max_vehicle_diameter_in"])
                length_in = min(base_length_in * l_scale, constraints["max_vehicle_length_in"])
                total_mass_lb = min(base_mass_lb * m_scale, constraints["max_total_mass_lb"])
                candidates.append(evaluate_candidate(diameter_in, length_in, total_mass_lb))

    ranked = sorted(
        candidates,
        key=lambda item: item.get("objective_error_pct") if item.get("objective_error_pct") is not None else 1e9,
    )
    if ranked:
        best = ranked[0]["rocket"]
        base_d = best["diameter_in"]
        base_l = best["length_in"]
        base_m = best["total_mass_lb"]
        refine_scales = [0.9, 0.95, 1.0, 1.05, 1.1]
        for d_scale in refine_scales:
            for l_scale in refine_scales:
                for m_scale in refine_scales:
                    diameter_in = min(base_d * d_scale, constraints["max_vehicle_diameter_in"])
                    length_in = min(base_l * l_scale, constraints["max_vehicle_length_in"])
                    total_mass_lb = min(base_m * m_scale, constraints["max_total_mass_lb"])
                    candidates.append(evaluate_candidate(diameter_in, length_in, total_mass_lb))
        ranked = sorted(
            candidates,
            key=lambda item: item.get("objective_error_pct") if item.get("objective_error_pct") is not None else 1e9,
        )
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for idx, item in enumerate(ranked[:5]):
        path = out_dir / f"motor_first_rocket_{idx}.json"
        payload = {"rocket": item["rocket"], "motor_metrics": motor_metrics}
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        item["artifacts"] = {"rocket_config": str(path)}

    summary = {
        "status": "ok" if ranked else "no_candidates",
        "candidate_count": len(candidates),
        "viable_count": sum(1 for item in candidates if item.get("within_tolerance")),
        "motor_metrics": motor_metrics,
    }
    return {"summary": summary, "candidates": candidates, "ranked": ranked}
