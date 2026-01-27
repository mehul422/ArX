import unittest

from app.engine.optimizer.input_optimizer import run_input_optimization


class InputOptimizerTests(unittest.TestCase):
    def test_optimizer_requires_target_apogee(self):
        with self.assertRaises(ValueError):
            run_input_optimization({})

    def test_optimizer_returns_recommended_values(self):
        result = run_input_optimization(
            {
                "target_apogee_m": 1500.0,
                "altitude_margin_m": 50.0,
                "max_mach": 0.9,
                "max_diameter_m": 0.1524,
                "payload_mass_kg": 12.5,
                "target_thrust_n": 15000.0,
                "constraints": {"max_total_mass_kg": 250.0},
            },
            iterations=5,
            population_size=5,
        )
        self.assertIn("recommended", result)
        self.assertIn("summary", result)
        self.assertIn("iterations", result)
        self.assertGreater(len(result["iterations"]), 0)
