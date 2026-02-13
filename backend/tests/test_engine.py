import os
import unittest

from app.core.config import get_settings
from app.engine.openmotor.internal_ballistics import run_internal_ballistics
from app.engine.openrocket.runner import run_openrocket_simulation
from app.engine.optimizer.evolutionary import run_evolutionary_optimization


class EngineTests(unittest.TestCase):
    def test_internal_ballistics_outputs(self):
        result = run_internal_ballistics(
            {
                "chamber_pressure": 3.0e6,
                "burn_time": 2.0,
                "throat_area": 0.0004,
                "c_star": 1500.0,
            }
        )
        self.assertIn("total_impulse", result)
        self.assertGreater(result["total_impulse"], 0)

    def test_evolutionary_optimization_outputs(self):
        result = run_evolutionary_optimization({"population_size": 10, "iterations": 5})
        self.assertIn("best_candidate", result)
        self.assertIn("best_score", result)

    def test_openrocket_requires_jar(self):
        os.environ["OPENROCKET_JAR"] = ""
        get_settings.cache_clear()
        with self.assertRaises(RuntimeError):
            run_openrocket_simulation({})
