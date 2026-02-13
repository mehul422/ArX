from pathlib import Path
import unittest

from app.module_r.ork_parser import parse_ork_to_assembly


class OrkRegressionTests(unittest.TestCase):
    def test_parse_existing_legacy_ork_fixture(self):
        fixture = (
            Path(__file__).resolve().parents[0]
            / "module_r"
            / "module_r_legacy_0c7e791a823342e7922d75a67476650a.ork"
        )
        self.assertTrue(fixture.exists())
        result = parse_ork_to_assembly(str(fixture))
        self.assertGreater(result.assembly.global_diameter_m, 0.0)
        self.assertTrue(result.assembly.body_tubes)
        self.assertTrue(result.assembly.fin_sets)

    def test_parse_parametric_ork_fixture_when_present(self):
        fixture = (
            Path(__file__).resolve().parents[0]
            / "module_r"
            / "module_r_parametric_14aa09282cce4e7b9d0751525c9ff58f.ork"
        )
        if not fixture.exists():
            self.skipTest("parametric ORK fixture not present in local workspace")
        result = parse_ork_to_assembly(str(fixture))
        self.assertGreater(result.assembly.global_diameter_m, 0.0)
        self.assertTrue(result.assembly.body_tubes)
