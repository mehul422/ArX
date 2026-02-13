import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.engine.openrocket.runner import run_openrocket_simulation


class OpenRocketIntegrationTests(unittest.TestCase):
    def test_openrocket_metrics_from_files(self):
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
        }
        result = run_openrocket_simulation(params)
        self.assertIn("cg", result)
        self.assertIn("cp", result)
        self.assertIn("total_mass", result)
        self.assertIn("stage_masses", result)
        self.assertIn("stability_margin", result)
