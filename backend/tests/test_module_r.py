import unittest
from pathlib import Path

from app.module_r.generator import run_auto_build
from app.module_r.schemas import AutoBuildConstraints, AutoBuildRequest, Bulkhead, Stage


class ModuleRTests(unittest.TestCase):
    def test_bulkhead_must_be_at_top(self):
        with self.assertRaises(ValueError):
            Stage(
                id="stage-1",
                name="Stage 1",
                length_m=1.0,
                diameter_m=0.1,
                motor_mount={
                    "id": "mount-1",
                    "name": "Mount",
                    "outer_diameter_m": 0.09,
                    "inner_diameter_m": 0.08,
                    "length_m": 0.9,
                    "position_from_bottom_m": 0.0,
                    "is_motor_mount": True,
                },
                bulkhead=Bulkhead(
                    id="bulk-1",
                    name="Bulk",
                    height_m=0.01,
                    material="Phenolic",
                    position_from_top_m=0.02,
                ),
            )

    def test_auto_build_from_ric(self):
        ric_path = (
            Path(__file__).resolve().parents[0]
            / "stress250k_single"
            / "auto_template.ric"
        )
        request = AutoBuildRequest(
            ric_path=str(ric_path),
            constraints=AutoBuildConstraints(
                upper_length_m=2.5,
                upper_mass_kg=10.0,
                target_apogee_m=1000.0,
            ),
            include_ballast=False,
            include_telemetry=True,
            include_parachute=True,
        )
        response = run_auto_build(request)
        self.assertGreater(response.assembly.global_diameter_m, 0.0)
        self.assertTrue(response.assembly.stages)
        self.assertTrue(response.assembly.fin_sets)
