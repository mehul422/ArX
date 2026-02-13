from pathlib import Path

from app.module_r.generator import run_auto_build
from app.module_r.schemas import AutoBuildConstraints, AutoBuildRequest


def _total_length_m(assembly) -> float:
    return (
        assembly.nose_cone.length_m
        + sum(stage.length_m for stage in assembly.stages)
        + sum(tube.length_m for tube in assembly.body_tubes)
    )


def _payload_mass_kg(assembly) -> float:
    total = 0.0
    for tube in assembly.body_tubes:
        for child in tube.children:
            if getattr(child, "type", None) == "telemetry":
                total += child.mass_kg
    return total


def test_complex_winner_logic_respects_constraints_and_structure():
    ric_path = (
        Path(__file__).resolve().parents[1]
        / "stress250k_single"
        / "auto_template.ric"
    )
    request = AutoBuildRequest(
        ric_path=str(ric_path),
        constraints=AutoBuildConstraints(
            upper_length_m=1.6,
            upper_mass_kg=6.0,
            target_apogee_m=15000.0,  # difficult target forces scorer tradeoffs
        ),
        include_ballast=True,
        include_telemetry=True,
        include_parachute=True,
        name="Complex Candidate Winner",
    )
    response = run_auto_build(request)
    assembly = response.assembly

    # Hard constraints
    assert _total_length_m(assembly) <= request.constraints.upper_length_m + 1e-6
    assert _payload_mass_kg(assembly) <= request.constraints.upper_mass_kg + 1e-6

    # Complex structure requirements
    assert len(assembly.body_tubes) >= 2
    assert len(assembly.stages) >= 1
    assert any(
        getattr(child, "type", None) == "inner_tube" and not child.is_motor_mount
        for tube in assembly.body_tubes
        for child in tube.children
    )
    assert all(stage.bulkhead.position_from_top_m == 0.0 for stage in assembly.stages)

    stage_ids = {stage.id for stage in assembly.stages}
    assert assembly.fin_sets
    assert all(fin.parent_tube_id in stage_ids for fin in assembly.fin_sets)
    assert assembly.metadata.get("winner_score") is not None
