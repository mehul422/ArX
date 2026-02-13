from __future__ import annotations

from dataclasses import dataclass
from itertools import islice, product
import math
import random
from typing import Iterable

from app.engine.openmotor_ai.ballistics import aggregate_metrics
from app.engine.openmotor_ai.ballistics import _simulate_ballistics_internal
from app.engine.openmotor_ai.ric_parser import load_ric
from app.engine.openmotor_ai.spec import spec_from_ric
from app.module_r.library import ComponentLibrary
from app.module_r.models import (
    CandidateBodyTube,
    CandidateFinSet,
    CandidateInnerTube,
    CandidateMassItem,
    CandidateNoseCone,
    CandidateRocket,
    CandidateStage,
    LibraryComponent,
    MotorSpec,
)
from app.module_r.schemas import (
    AutoBuildConstraints,
    BallastMass,
    BodyTube,
    Bulkhead,
    FinSet,
    InnerTube,
    NoseCone,
    ParachuteRef,
    RocketAssembly,
    Stage,
    TelemetryMass,
)


@dataclass(frozen=True)
class ScoringConfig:
    apogee_weight: float = 0.65
    mass_eff_weight: float = 0.20
    stability_weight: float = 0.15


@dataclass(frozen=True)
class MotorFlightProfile:
    diameter_m: float
    length_m: float
    total_impulse_ns: float
    burn_time_s: float
    propellant_mass_kg: float
    average_thrust_n: float


def _is_high_load_case(
    motors: list[MotorFlightProfile],
    stage_count: int,
    target_apogee_m: float | None,
) -> bool:
    total_impulse = sum(m.total_impulse_ns for m in motors)
    avg_thrust = sum(m.average_thrust_n for m in motors)
    return (
        stage_count >= 2
        or total_impulse >= 150_000.0
        or avg_thrust >= 2_000.0
        or (target_apogee_m is not None and target_apogee_m >= 12_000.0)
    )


def _select_body_tube_material() -> tuple[str, str]:
    return ("Aluminum 6063-T6", "default_structural_fallback")


def _select_stage_shell_material(
    *,
    motors: list[MotorFlightProfile],
    stage_count: int,
    target_apogee_m: float | None,
) -> tuple[str, str]:
    return ("Aluminum 6063-T6", "default_stage_shell")


def _select_bulkhead_and_mount_material(
    *,
    motors: list[MotorFlightProfile],
    stage_count: int,
    target_apogee_m: float | None,
) -> tuple[str, str]:
    if _is_high_load_case(motors, stage_count, target_apogee_m):
        return ("Phenolic", "thermal_or_load_resistant_bulkhead")
    return ("Aluminum 6063-T6", "default_bulkhead_mount_fallback")


def _select_nose_material(
    *,
    motors: list[MotorFlightProfile],
    stage_count: int,
    target_apogee_m: float | None,
) -> tuple[str, str]:
    if _is_high_load_case(motors, stage_count, target_apogee_m):
        return ("Fiberglass", "high_load_nose")
    return ("Aluminum 6063-T6", "default_nose_fallback")


def _select_fin_material(
    *,
    motors: list[MotorFlightProfile],
    stage_count: int,
    target_apogee_m: float | None,
) -> tuple[str, str]:
    if _is_high_load_case(motors, stage_count, target_apogee_m):
        return ("Fiberglass", "high_load_fins")
    return ("Aluminum 6063-T6", "default_fin_fallback")


def _motor_spec_from_ric(ric_path: str) -> MotorSpec:
    ric = load_ric(ric_path)
    spec = spec_from_ric(ric)
    if not spec.grains:
        raise ValueError("no grains found in .ric")
    length_m = sum(grain.length_m for grain in spec.grains)
    diameter_m = max(grain.diameter_m for grain in spec.grains)
    if length_m <= 0 or diameter_m <= 0:
        raise ValueError("invalid motor dimensions from .ric")
    return MotorSpec(diameter_m=diameter_m, length_m=length_m)


def _motor_profile_from_ric(ric_path: str) -> MotorFlightProfile:
    ric = load_ric(ric_path)
    spec = spec_from_ric(ric)
    if not spec.grains:
        raise ValueError("no grains found in .ric")

    length_m = sum(grain.length_m for grain in spec.grains)
    diameter_m = max(grain.diameter_m for grain in spec.grains)
    if length_m <= 0 or diameter_m <= 0:
        raise ValueError("invalid motor dimensions from .ric")

    # Compute propellant mass directly from grain geometry.
    propellant_mass_kg = 0.0
    for grain in spec.grains:
        r_outer = grain.diameter_m / 2.0
        r_core = grain.core_diameter_m / 2.0
        propellant_mass_kg += (
            math.pi * max(r_outer * r_outer - r_core * r_core, 0.0) * grain.length_m
        ) * max(spec.propellant.density_kg_m3, 1.0)

    # Use deterministic internal ballistics to estimate impulse and burn.
    try:
        steps = _simulate_ballistics_internal(spec)
        metrics = aggregate_metrics(spec, steps)
    except Exception:
        metrics = {}

    total_impulse_ns = float(metrics.get("total_impulse", 0.0) or 0.0)
    burn_time_s = float(metrics.get("burn_time", 0.0) or 0.0)

    if total_impulse_ns <= 0.0 or burn_time_s <= 0.0:
        # Fallback to conservative approximation when simulation does not converge.
        isp_guess_s = 130.0
        total_impulse_ns = max(50.0, propellant_mass_kg * 9.80665 * isp_guess_s)
        burn_time_s = max(0.8, length_m * 2.2)

    average_thrust_n = total_impulse_ns / max(burn_time_s, 1e-6)
    return MotorFlightProfile(
        diameter_m=diameter_m,
        length_m=length_m,
        total_impulse_ns=total_impulse_ns,
        burn_time_s=burn_time_s,
        propellant_mass_kg=max(propellant_mass_kg, 0.01),
        average_thrust_n=average_thrust_n,
    )


def generate_candidates(
    ric_data: list[str],
    constraints: AutoBuildConstraints,
    *,
    include_ballast: bool,
    include_telemetry: bool,
    include_parachute: bool,
    requested_stage_count: int | None = None,
    library: ComponentLibrary | None = None,
    random_seed: int | None = None,
) -> list[CandidateRocket]:
    source_motors = [_motor_profile_from_ric(path) for path in ric_data]
    max_motor_dia = max(motor.diameter_m for motor in source_motors)
    lib = library or ComponentLibrary.load(motor_diameter_m=max_motor_dia)

    compatible_tubes = [
        part
        for part in lib.parts_by_category("body_tube")
        if (part.inner_diameter_m or 0.0) > max_motor_dia + 0.002
    ]
    if not compatible_tubes:
        # Synthetic fallback sized from motor geometry for guaranteed feasibility.
        compatible_tubes = [
            LibraryComponent(
                id="synthetic-body-1",
                vendor="synthetic",
                name="Synthetic Body Tube",
                category="body_tube",
                shape="cylinder",
                material="Aluminum 6063-T6",
                hollow=True,
                outer_diameter_m=max_motor_dia + 0.008,
                inner_diameter_m=max_motor_dia + 0.004,
                length_m=max(0.5, constraints.upper_length_m * 0.4),
                wall_thickness_m=0.002,
            )
        ]
    else:
        # Always include one tight synthetic airframe as a high-ballistic-coefficient option.
        compatible_tubes.append(
            LibraryComponent(
                id="synthetic-body-tight",
                vendor="synthetic",
                name="Synthetic Tight Body Tube",
                category="body_tube",
                shape="cylinder",
                material="Aluminum 6063-T6",
                hollow=True,
                outer_diameter_m=max_motor_dia + 0.008,
                inner_diameter_m=max_motor_dia + 0.004,
                length_m=max(0.45, constraints.upper_length_m * 0.35),
                wall_thickness_m=0.002,
            )
        )

    compatible_nose = [
        part
        for part in lib.parts_by_category("nose_cone")
        if part.outer_diameter_m is not None
    ]
    if not compatible_nose:
        compatible_nose = [
            LibraryComponent(
                id="synthetic-nose-1",
                vendor="synthetic",
                name="Synthetic Ogive Nose",
                category="nose_cone",
                shape="ogive",
                material="Aluminum 6063-T6",
                hollow=False,
                outer_diameter_m=(compatible_tubes[0].outer_diameter_m or (max_motor_dia + 0.014)),
                length_m=max(0.14, constraints.upper_length_m * 0.12),
            )
        ]
    else:
        compatible_nose.append(
            LibraryComponent(
                id="synthetic-nose-tight",
                vendor="synthetic",
                name="Synthetic Low-Drag Nose",
                category="nose_cone",
                shape="ogive",
                material="Aluminum 6063-T6",
                hollow=False,
                outer_diameter_m=max_motor_dia + 0.008,
                length_m=max(0.16, constraints.upper_length_m * 0.14),
            )
        )

    fin_parts = list(lib.parts_by_category("fin_set"))
    rng = random.Random(random_seed) if random_seed is not None else None
    if rng is not None:
        rng.shuffle(compatible_tubes)
        rng.shuffle(compatible_nose)
        rng.shuffle(fin_parts)

    if not fin_parts:
        raise ValueError("no fin sets in component library")

    stage_layouts: list[list[MotorFlightProfile]]
    if requested_stage_count is not None:
        # Respect the user's explicit AUTO-mode stage count selection (1-5).
        count = max(1, min(5, int(requested_stage_count)))
        if len(source_motors) == 1:
            stage_layouts = [[source_motors[0]] * count]
        else:
            staged: list[MotorFlightProfile] = []
            for idx in range(count):
                source_idx = min(idx, len(source_motors) - 1)
                staged.append(source_motors[source_idx])
            stage_layouts = [staged]

        min_required_length = (
            sum(motor.length_m + 0.01 for motor in stage_layouts[0])  # stage + bulkhead
            + 0.12  # minimum nose length
            + 0.1  # minimum free body budget required by generator
        )
    elif len(source_motors) > 1:
        stage_layouts = [source_motors]
    else:
        base = source_motors[0]
        max_stage_count = max(
            1,
            min(5, int(max(constraints.upper_length_m - 0.2, 0.0) / max(base.length_m + 0.05, 0.1))),
        )
        stage_layouts = [[base] * count for count in range(1, max_stage_count + 1)]

    candidates: list[CandidateRocket] = []
    candidate_id = 0
    for (
        stage_motors,
        tube_part,
        nose_part,
        fin_part,
        body_ratio,
        fin_position_ratio,
        fin_scale,
    ) in product(
        stage_layouts,
        islice(compatible_tubes, 0, 5),
        islice(compatible_nose, 0, 4),
        islice(fin_parts, 0, 3),
        (0.5, 0.65, 0.8, 0.95, 1.0),
        (0.0, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8),
        (0.8, 0.95, 1.0, 1.15, 1.3),
    ):
        global_diameter = tube_part.outer_diameter_m or (max_motor_dia + 0.01)
        if abs((nose_part.outer_diameter_m or global_diameter) - global_diameter) > 0.03:
            continue

        bulkhead_height = 0.01
        target_apogee = constraints.target_apogee_m
        stage_count = len(stage_motors)
        stage_shell_material, stage_shell_reason = _select_stage_shell_material(
            motors=stage_motors,
            stage_count=stage_count,
            target_apogee_m=target_apogee,
        )
        bulkhead_material, bulkhead_reason = _select_bulkhead_and_mount_material(
            motors=stage_motors,
            stage_count=stage_count,
            target_apogee_m=target_apogee,
        )
        body_tube_material, body_tube_reason = _select_body_tube_material()
        nose_material, nose_reason = _select_nose_material(
            motors=stage_motors,
            stage_count=stage_count,
            target_apogee_m=target_apogee,
        )
        fin_material, fin_reason = _select_fin_material(
            motors=stage_motors,
            stage_count=stage_count,
            target_apogee_m=target_apogee,
        )
        stages: list[CandidateStage] = []
        for stage_idx, motor in enumerate(stage_motors, start=1):
            mount_outer = min(global_diameter - 0.001, motor.diameter_m + 0.002)
            mount_inner = max(motor.diameter_m + 0.0005, mount_outer - 0.001)
            mount = CandidateInnerTube(
                id=f"stage-{stage_idx}-mount",
                name=f"Stage {stage_idx} Motor Mount",
                outer_diameter_m=mount_outer,
                inner_diameter_m=mount_inner,
                length_m=motor.length_m,
                position_from_bottom_m=0.0,
                is_motor_mount=True,
            )
            stages.append(
                CandidateStage(
                    id=f"stage-{stage_idx}",
                    name=f"Stage {stage_idx}",
                    length_m=motor.length_m + bulkhead_height,
                    diameter_m=global_diameter,
                    motor_mount=mount,
                    bulkhead_height_m=bulkhead_height,
                    bulkhead_material=bulkhead_material,
                )
            )

        total_stage_length = sum(stage.length_m for stage in stages)
        nose_length = max(0.12, min((nose_part.length_m or global_diameter * 3.0), global_diameter * 4.0))
        free_length = constraints.upper_length_m - total_stage_length - nose_length
        if free_length <= 0.1:
            # Do not hard-stop generation on tight user constraints; keep building
            # a structurally valid candidate and let filtering/scoring decide.
            free_length = 0.1
        total_body_length = max(0.2, free_length * body_ratio)

        # Complex-rocket behavior: use two body tubes when possible.
        has_second_tube = total_body_length > 0.24
        segment_1_len = total_body_length * (0.6 if has_second_tube else 1.0)
        segment_2_len = total_body_length - segment_1_len

        body_tubes: list[CandidateBodyTube] = [
            CandidateBodyTube(
                id="body-1",
                name="Primary Body Tube",
                length_m=segment_1_len,
                diameter_m=global_diameter,
                wall_thickness_m=tube_part.wall_thickness_m or 0.002,
                material=body_tube_material,
            )
        ]
        if has_second_tube:
            body_tubes.append(
                CandidateBodyTube(
                    id="body-2",
                    name="Upper Body Tube",
                    length_m=max(0.1, segment_2_len),
                    diameter_m=global_diameter,
                    wall_thickness_m=tube_part.wall_thickness_m or 0.002,
                    material=body_tube_material,
                )
            )

        if include_parachute:
            body_tubes[-1].parachute_diameter_m = global_diameter * 8.0
            body_tubes[-1].parachute_position_m = body_tubes[-1].length_m * 0.7

        if include_telemetry:
            bay_outer = min(global_diameter * 0.6, (tube_part.inner_diameter_m or global_diameter) * 0.8)
            bay_inner = max(0.005, bay_outer - 0.004)
            body_tubes[-1].inner_tubes.append(
                CandidateInnerTube(
                    id=f"{body_tubes[-1].id}-av-bay",
                    name="Electronics Inner Tube",
                    outer_diameter_m=bay_outer,
                    inner_diameter_m=bay_inner,
                    length_m=max(0.08, body_tubes[-1].length_m * 0.35),
                    position_from_bottom_m=body_tubes[-1].length_m * 0.2,
                    is_motor_mount=False,
                )
            )
            body_tubes[-1].masses.append(
                CandidateMassItem(
                    id="telemetry-1",
                    name="Telemetry Module",
                    mass_kg=min(max(constraints.upper_mass_kg * 0.1, 0.08), 0.9),
                    position_from_bottom_m=body_tubes[-1].length_m * 0.25,
                    item_type="telemetry",
                )
            )

        if include_ballast:
            ballast_mass = max(0.05, constraints.upper_mass_kg * 0.005)
            if constraints.target_apogee_m and constraints.target_apogee_m >= 10_000:
                ballast_mass *= 0.35
            body_tubes[0].masses.append(
                CandidateMassItem(
                    id="ballast-1",
                    name="Ballast",
                    mass_kg=min(ballast_mass, 1.0),
                    position_from_bottom_m=body_tubes[0].length_m * 0.1,
                    item_type="ballast",
                )
            )

        fin_count = int(fin_part.metadata.get("fin_count", 4)) if fin_part.metadata else 4
        fin_position_from_bottom = max(0.0, stages[0].length_m * fin_position_ratio)
        fins = CandidateFinSet(
            id="finset-1",
            name=fin_part.name,
            parent_tube_id=stages[0].id,
            fin_count=max(3, min(fin_count, 6)),
            root_chord_m=max(0.04, (fin_part.root_chord_m or global_diameter * 1.8) * fin_scale),
            tip_chord_m=max(0.02, (fin_part.tip_chord_m or global_diameter * 1.0) * fin_scale),
            span_m=max(0.03, (fin_part.span_m or global_diameter * 1.5) * fin_scale),
            sweep_m=max(0.0, fin_part.sweep_m or 0.0),
            thickness_m=0.003,
            position_from_bottom_m=fin_position_from_bottom,
        )

        candidate_id += 1
        candidate = CandidateRocket(
            id=f"cand-{candidate_id}",
            name=f"Auto Candidate {candidate_id}",
            global_diameter_m=global_diameter,
            nose_cone=CandidateNoseCone(
                id="nose-1",
                name=nose_part.name,
                nose_type="OGIVE",
                length_m=nose_length,
                diameter_m=global_diameter,
                material=nose_material,
            ),
            stages=stages,
            body_tubes=body_tubes,
            fin_set=fins,
            metadata={
                "source_tube": tube_part.name,
                "source_tube_material": body_tube_material,
                "source_nose": nose_part.name,
                "source_nose_material": nose_material,
                "source_fin": fin_part.name,
                "source_fin_material": fin_material,
                "fin_position_ratio": fin_position_ratio,
                "fin_scale": fin_scale,
                "stage_count": len(stage_motors),
                "stage_shell_material": stage_shell_material,
                "bulkhead_material": bulkhead_material,
                "motor_mount_material": bulkhead_material,
                "parachute_material": "Ripstop nylon",
                "material_reason_stage_shell": stage_shell_reason,
                "material_reason_body_tube": body_tube_reason,
                "material_reason_bulkhead_and_mount": bulkhead_reason,
                "material_reason_nose": nose_reason,
                "material_reason_fin": fin_reason,
                "material_reason_parachute": "surface_fabric_recovery_component",
            },
        )
        candidate.total_mass_kg = estimate_total_mass_kg(candidate, lib)
        candidate.predicted_apogee_m = estimate_apogee_m(candidate, stage_motors)
        candidate.stability_margin_cal = estimate_stability_margin_cal(candidate)
        candidates.append(candidate)

    return candidates


def filter_candidates(
    candidates: Iterable[CandidateRocket],
    constraints: AutoBuildConstraints,
    *,
    motor_specs: list[MotorSpec] | None = None,
    min_stability_cal: float | None = 1.0,
    enforce_length: bool = True,
    enforce_mass: bool = True,
    rejection_counts: dict[str, int] | None = None,
) -> list[CandidateRocket]:
    accepted: list[CandidateRocket] = []
    max_motor_dia = max((m.diameter_m for m in (motor_specs or [])), default=0.0)
    max_motor_len = max((m.length_m for m in (motor_specs or [])), default=0.0)

    def reject(reason: str) -> None:
        if rejection_counts is None:
            return
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1

    for candidate in candidates:
        if not candidate.stages or not candidate.body_tubes:
            reject("structure")
            continue
        if any(stage.motor_mount.outer_diameter_m >= stage.diameter_m for stage in candidate.stages):
            reject("motor_mount_geometry")
            continue
        if max_motor_dia and any(
            (stage.motor_mount.inner_diameter_m or 0.0) < max_motor_dia for stage in candidate.stages
        ):
            reject("motor_diameter_fit")
            continue
        if max_motor_len and any(stage.motor_mount.length_m < max_motor_len for stage in candidate.stages):
            reject("motor_length_fit")
            continue
        total_length = candidate.nose_cone.length_m
        total_length += sum(stage.length_m for stage in candidate.stages)
        total_length += sum(tube.length_m for tube in candidate.body_tubes)
        if enforce_length and total_length > constraints.upper_length_m:
            reject("length")
            continue
        if enforce_mass and candidate.total_mass_kg > constraints.upper_mass_kg:
            reject("mass")
            continue
        if min_stability_cal is not None and candidate.stability_margin_cal < min_stability_cal:
            reject("stability")
            continue
        accepted.append(candidate)
    return accepted


def score_candidates(
    candidates: Iterable[CandidateRocket],
    target_apogee_m: float | None,
    *,
    config: ScoringConfig | None = None,
) -> list[CandidateRocket]:
    cfg = config or ScoringConfig()
    target = target_apogee_m or 1000.0
    ranked: list[CandidateRocket] = []
    for candidate in candidates:
        apogee_err = abs(candidate.predicted_apogee_m - target) / max(target, 1.0)
        mass_eff = candidate.total_mass_kg / max(0.1, candidate.predicted_apogee_m / 1000.0)
        stability_penalty = max(0.0, 1.0 - min(candidate.stability_margin_cal / 2.0, 1.0))
        score = (
            cfg.apogee_weight * apogee_err
            + cfg.mass_eff_weight * mass_eff
            + cfg.stability_weight * stability_penalty
        )
        candidate.score = float(score)
        ranked.append(candidate)
    ranked.sort(key=lambda candidate: candidate.score)
    return ranked


def estimate_total_mass_kg(candidate: CandidateRocket, library: ComponentLibrary) -> float:
    total = 0.0
    stage_shell_material = str(candidate.metadata.get("stage_shell_material") or "Aluminum 6063-T6")
    motor_mount_material = str(candidate.metadata.get("motor_mount_material") or "Aluminum 6063-T6")
    fin_material = str(candidate.metadata.get("source_fin_material") or "Aluminum 6063-T6")
    for stage in candidate.stages:
        mat = library.material(stage_shell_material)
        r_o = stage.diameter_m / 2.0
        wall = 0.002
        r_i = max(r_o - wall, 0.0)
        total += 3.14159 * (r_o * r_o - r_i * r_i) * stage.length_m * mat.density_kg_m3
        bulk_mat = library.material(stage.bulkhead_material)
        bulk_r = stage.diameter_m / 2.0
        total += 3.14159 * bulk_r * bulk_r * stage.bulkhead_height_m * bulk_mat.density_kg_m3 * 0.7
        mount_mat = library.material(motor_mount_material)
        mr_o = stage.motor_mount.outer_diameter_m / 2.0
        mr_i = stage.motor_mount.inner_diameter_m / 2.0
        total += (
            3.14159 * max(mr_o * mr_o - mr_i * mr_i, 0.0) * stage.motor_mount.length_m * mount_mat.density_kg_m3
        )
    for tube in candidate.body_tubes:
        mat = library.material(tube.material)
        r_o = tube.diameter_m / 2.0
        wall = tube.wall_thickness_m
        r_i = max(r_o - wall, 0.0)
        total += 3.14159 * (r_o * r_o - r_i * r_i) * tube.length_m * mat.density_kg_m3
        for child in tube.inner_tubes:
            alu = library.material("Aluminum")
            c_ro = child.outer_diameter_m / 2.0
            c_ri = child.inner_diameter_m / 2.0
            total += 3.14159 * max(c_ro * c_ro - c_ri * c_ri, 0.0) * child.length_m * alu.density_kg_m3
        total += sum(item.mass_kg for item in tube.masses)
    nose_mat = library.material(candidate.nose_cone.material)
    r = candidate.nose_cone.diameter_m / 2.0
    total += ((3.14159 * r * r * candidate.nose_cone.length_m) / 3.0) * nose_mat.density_kg_m3 * 0.35
    fin = candidate.fin_set
    fin_area = ((fin.root_chord_m + fin.tip_chord_m) * 0.5) * fin.span_m
    fin_vol = fin_area * fin.thickness_m
    fin_mat = library.material(fin_material)
    total += fin.fin_count * fin_vol * fin_mat.density_kg_m3
    return total


def estimate_apogee_m(candidate: CandidateRocket, motor_profiles: list[MotorFlightProfile]) -> float:
    total_impulse_ns = sum(profile.total_impulse_ns for profile in motor_profiles)
    total_burn_s = sum(profile.burn_time_s for profile in motor_profiles)
    total_prop_mass_kg = sum(profile.propellant_mass_kg for profile in motor_profiles)
    if total_impulse_ns <= 0.0:
        return 0.0

    # Lightweight 1-DOF vertical simulation with variable mass and drag.
    g = 9.80665
    rho = 1.225
    area = math.pi * (candidate.global_diameter_m / 2.0) ** 2
    fin = candidate.fin_set
    fin_area = ((fin.root_chord_m + fin.tip_chord_m) * 0.5) * fin.span_m * fin.fin_count
    fin_area_ratio = fin_area / max(area, 1e-6)
    # Approximate Cd: base body + fin contribution.
    cd = max(0.35, min(1.15, 0.38 + 0.065 * fin_area_ratio))

    inert_motor_mass = max(0.12 * total_prop_mass_kg + 0.09 * len(motor_profiles), 0.05)
    prop_mass = max(total_prop_mass_kg, 0.02)
    dry_mass = max(candidate.total_mass_kg + inert_motor_mass, 0.25)
    loaded_mass = dry_mass + prop_mass
    burn_time = max(0.6, total_burn_s)
    avg_thrust = total_impulse_ns / burn_time
    thrust_scale = 1.0 if total_impulse_ns > 10_000 else 0.75

    dt = 0.02
    t = 0.0
    h = 0.0
    v = 0.0
    m = dry_mass + prop_mass
    max_h = 0.0

    while t < burn_time:
        drag = 0.5 * rho * cd * area * v * abs(v)
        a = ((avg_thrust * thrust_scale) - drag - m * g) / m
        v += a * dt
        h += v * dt
        max_h = max(max_h, h)
        m = max(dry_mass, m - (prop_mass / burn_time) * dt)
        t += dt

    # Coast to apogee
    while v > 0 and h < 300000:
        drag = 0.5 * rho * cd * area * v * abs(v)
        a = (-drag - m * g) / m
        v += a * dt
        h += v * dt
        max_h = max(max_h, h)
        t += dt
        if t > 240:
            break

    return max(0.0, min(max_h, 300000.0))


def estimate_stability_margin_cal(candidate: CandidateRocket) -> float:
    d = candidate.global_diameter_m
    if d <= 0:
        return 0.0
    total_length = candidate.nose_cone.length_m
    total_length += sum(stage.length_m for stage in candidate.stages)
    total_length += sum(tube.length_m for tube in candidate.body_tubes)

    cg = total_length * 0.45
    cp = (
        candidate.nose_cone.length_m * 0.666
        + total_length * 0.42
        + candidate.fin_set.position_from_bottom_m
        + candidate.fin_set.root_chord_m * 0.45
    )
    return (cp - cg) / d


def candidate_to_assembly(candidate: CandidateRocket) -> RocketAssembly:
    stages = [
        Stage(
            id=stage.id,
            name=stage.name,
            length_m=stage.length_m,
            diameter_m=stage.diameter_m,
            motor_mount=InnerTube(
                id=stage.motor_mount.id,
                name=stage.motor_mount.name,
                outer_diameter_m=stage.motor_mount.outer_diameter_m,
                inner_diameter_m=stage.motor_mount.inner_diameter_m,
                length_m=stage.motor_mount.length_m,
                position_from_bottom_m=stage.motor_mount.position_from_bottom_m,
                is_motor_mount=True,
            ),
            bulkhead=Bulkhead(
                id=f"{stage.id}-bulkhead",
                name=f"{stage.name} Bulkhead",
                height_m=stage.bulkhead_height_m,
                material=stage.bulkhead_material,
                position_from_top_m=0.0,
            ),
        )
        for stage in candidate.stages
    ]

    tubes: list[BodyTube] = []
    for tube in candidate.body_tubes:
        children: list[InnerTube | ParachuteRef | TelemetryMass | BallastMass] = []
        for inner in tube.inner_tubes:
            children.append(
                InnerTube(
                    id=inner.id,
                    name=inner.name,
                    outer_diameter_m=inner.outer_diameter_m,
                    inner_diameter_m=inner.inner_diameter_m,
                    length_m=inner.length_m,
                    position_from_bottom_m=inner.position_from_bottom_m,
                    is_motor_mount=inner.is_motor_mount,
                )
            )
        if tube.parachute_diameter_m and tube.parachute_position_m is not None:
            children.append(
                ParachuteRef(
                    id=f"{tube.id}-parachute",
                    name="Recovery Parachute",
                    library_id="default",
                    diameter_m=tube.parachute_diameter_m,
                    position_from_bottom_m=tube.parachute_position_m,
                )
            )
        for mass in tube.masses:
            if mass.item_type == "ballast":
                children.append(
                    BallastMass(
                        id=mass.id,
                        name=mass.name,
                        mass_kg=mass.mass_kg,
                        position_from_bottom_m=mass.position_from_bottom_m,
                    )
                )
            else:
                children.append(
                    TelemetryMass(
                        id=mass.id,
                        name=mass.name,
                        mass_kg=mass.mass_kg,
                        position_from_bottom_m=mass.position_from_bottom_m,
                    )
                )
        tubes.append(
            BodyTube(
                id=tube.id,
                name=tube.name,
                length_m=tube.length_m,
                diameter_m=tube.diameter_m,
                wall_thickness_m=tube.wall_thickness_m,
                children=children,
            )
        )

    fin = candidate.fin_set
    return RocketAssembly(
        name=candidate.name,
        design_mode="AUTO",
        global_diameter_m=candidate.global_diameter_m,
        nose_cone=NoseCone(
            id=candidate.nose_cone.id,
            name=candidate.nose_cone.name,
            type=candidate.nose_cone.nose_type,
            length_m=candidate.nose_cone.length_m,
            diameter_m=candidate.nose_cone.diameter_m,
            material=candidate.nose_cone.material,
        ),
        stages=stages,
        body_tubes=tubes,
        fin_sets=[
            FinSet(
                id=fin.id,
                name=fin.name,
                parent_tube_id=fin.parent_tube_id,
                fin_count=fin.fin_count,
                root_chord_m=fin.root_chord_m,
                tip_chord_m=fin.tip_chord_m,
                span_m=fin.span_m,
                sweep_m=fin.sweep_m,
                thickness_m=fin.thickness_m,
                position_from_bottom_m=fin.position_from_bottom_m,
            )
        ],
        metadata={
            **candidate.metadata,
            "predicted_apogee_m": candidate.predicted_apogee_m,
            "total_mass_kg": candidate.total_mass_kg,
            "stability_margin_cal": candidate.stability_margin_cal,
            "winner_score": candidate.score,
        },
    )
