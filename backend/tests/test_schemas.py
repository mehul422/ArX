import unittest

from pydantic import ValidationError

from app.api.v1.schemas import OptimizationRequest, SimulationRequest


class SchemaTests(unittest.TestCase):
    def test_simulation_request_defaults(self):
        with self.assertRaises(ValidationError):
            SimulationRequest(rocket_path="/tmp/rocket.ork", motor_source="bundled")

    def test_optimization_request_defaults(self):
        data = OptimizationRequest()
        self.assertEqual(data.params, {})

    def test_simulation_request_valid(self):
        data = SimulationRequest(
            rocket_path="/tmp/rocket.ork", motor_source="bundled", motor_id="test.eng"
        )
        self.assertEqual(data.motor_id, "test.eng")
