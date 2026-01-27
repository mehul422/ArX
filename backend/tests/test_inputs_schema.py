import unittest

from pydantic import ValidationError

from app.api.v1.schemas import InputConstraints, UserInputRequest


class InputSchemaTests(unittest.TestCase):
    def test_requires_target_apogee(self):
        with self.assertRaises(ValidationError):
            UserInputRequest()

    def test_constraints_validation(self):
        with self.assertRaises(ValidationError):
            InputConstraints(max_total_mass_kg=-1.0)

    def test_invalid_margin(self):
        with self.assertRaises(ValidationError):
            UserInputRequest(target_apogee_m=1500.0, altitude_margin_m=-5.0)

    def test_invalid_max_mach(self):
        with self.assertRaises(ValidationError):
            UserInputRequest(target_apogee_m=1500.0, max_mach=-0.1)

    def test_invalid_optional_fields(self):
        with self.assertRaises(ValidationError):
            UserInputRequest(target_apogee_m=1500.0, max_diameter_m=-0.1)
        with self.assertRaises(ValidationError):
            UserInputRequest(target_apogee_m=1500.0, payload_mass_kg=-0.1)
        with self.assertRaises(ValidationError):
            UserInputRequest(target_apogee_m=1500.0, target_thrust_n=-0.1)

    def test_valid_input(self):
        data = UserInputRequest(
            target_apogee_m=1500.0,
            altitude_margin_m=50.0,
            max_mach=0.9,
            max_diameter_m=0.1524,
            payload_mass_kg=12.5,
            target_thrust_n=15000.0,
            constraints=InputConstraints(max_total_mass_kg=250.0),
        )
        self.assertEqual(data.target_apogee_m, 1500.0)
