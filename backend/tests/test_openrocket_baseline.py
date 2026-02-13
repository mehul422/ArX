import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engine.openrocket.runner import run_openrocket_simulation


class OpenRocketBaselineTests(unittest.TestCase):
    def test_baseline_metrics_within_tolerance(self):
        jar_path = os.getenv("OPENROCKET_JAR") or (
            "/Users/mehulverma422/Desktop/ArX/arx-os/backend/resources/jars/OpenRocket-15.03.jar"
        )
        rocket_path = os.getenv(
            "ORK_PATH",
            "/Users/mehulverma422/Desktop/ArX/arx-os/backend/tests/testforai/rocket.ork",
        )
        motor_path = os.getenv(
            "ENG_PATH",
            "/Users/mehulverma422/Desktop/ArX/arx-os/backend/tests/power1us.eng",
        )
        if not (os.path.exists(jar_path) and os.path.exists(rocket_path) and os.path.exists(motor_path)):
            self.skipTest("OpenRocket jar or input files not available")

        params = {
            "openrocket_jar": jar_path,
            "rocket_path": rocket_path,
            "motor_path": motor_path,
            "material_mode": "custom",
            "use_all_stages": True,
        }
        result = run_openrocket_simulation(params)

        # Baseline values from OpenRocket GUI (update when confirmed).
        expected = {
            "total_mass_lb": 187.0,
            "cg_in": 97.03,
            "cp_in": 112.0,
            "stage_masses_lb": {"0": 102.0, "1": 85.2},
            "stability_margin": 2.39,
        }

        def rel_err(actual, exp):
            return abs(actual - exp) / exp if exp else 0.0

        self.assertLessEqual(rel_err(result["total_mass_lb"], expected["total_mass_lb"]), 0.02)
        self.assertLessEqual(rel_err(result["cg_in"]["x"], expected["cg_in"]), 0.02)
        self.assertLessEqual(rel_err(result["cp_in"]["x"], expected["cp_in"]), 0.02)
        self.assertLessEqual(
            rel_err(result["stage_masses_lb"]["0"], expected["stage_masses_lb"]["0"]),
            0.02,
        )
        self.assertLessEqual(
            rel_err(result["stage_masses_lb"]["1"], expected["stage_masses_lb"]["1"]),
            0.02,
        )
        self.assertLessEqual(
            rel_err(result["stability_margin"], expected["stability_margin"]), 0.02
        )
