import unittest

from app.api.v1.schemas import OptimizationRequest


class SchemaTests(unittest.TestCase):
    def test_optimization_request_defaults(self):
        data = OptimizationRequest()
        self.assertEqual(data.params, {})
