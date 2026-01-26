import unittest

from app.api.v1.schemas import OptimizationRequest, SimulationRequest


class SchemaTests(unittest.TestCase):
    def test_simulation_request_defaults(self):
        data = SimulationRequest()
        self.assertEqual(data.params, {})

    def test_optimization_request_defaults(self):
        data = OptimizationRequest()
        self.assertEqual(data.params, {})
