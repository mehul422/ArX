import json
import unittest
from pathlib import Path

from app.engine.openmotor_ai.motor_first import run_motor_first_design
from app.engine.openmotor_ai.spec import BATESGrain, MotorConfig, MotorSpec, NozzleSpec, PropellantSpec, PropellantTab


class MotorFirstTests(unittest.TestCase):
    def _sample_motor_spec(self) -> MotorSpec:
        presets_path = Path(__file__).resolve().parents[1] / "resources" / "propellants" / "presets.json"
        data = json.loads(presets_path.read_text(encoding="utf-8"))
        preset = data[0]
        tabs = [
            PropellantTab(
                a=float(tab["a"]),
                n=float(tab["n"]),
                k=float(tab["k"]),
                m=float(tab["m"]),
                t=float(tab["t"]),
                min_pressure_pa=float(tab["minPressure"]),
                max_pressure_pa=float(tab["maxPressure"]),
            )
            for tab in preset["tabs"]
        ]
        propellant = PropellantSpec(
            name=preset["name"],
            density_kg_m3=float(preset["density"]),
            tabs=tabs,
        )
        grains = [
            BATESGrain(
                diameter_m=0.08,
                core_diameter_m=0.03,
                length_m=0.12,
                inhibited_ends="Neither",
            )
            for _ in range(3)
        ]
        nozzle = NozzleSpec(
            throat_diameter_m=0.02,
            exit_diameter_m=0.04,
            throat_length_m=0.0,
            conv_angle_deg=35.0,
            div_angle_deg=12.0,
            efficiency=1.0,
            erosion_coeff=0.0,
            slag_coeff=0.0,
        )
        config = MotorConfig(
            amb_pressure_pa=101325.0,
            burnout_thrust_threshold_n=0.1,
            burnout_web_threshold_m=2.54e-5,
            map_dim=500,
            max_mass_flux_kg_m2_s=1400.0,
            max_pressure_pa=1.2e7,
            min_port_throat_ratio=2.0,
            timestep_s=0.03,
        )
        return MotorSpec(config=config, propellant=propellant, grains=grains, nozzle=nozzle)

    def test_motor_first_design_runs(self):
        spec = self._sample_motor_spec()
        payload = {
            "propellant": {
                "name": spec.propellant.name,
                "density": spec.propellant.density_kg_m3,
                "tabs": [
                    {
                        "a": tab.a,
                        "n": tab.n,
                        "k": tab.k,
                        "m": tab.m,
                        "t": tab.t,
                        "minPressure": tab.min_pressure_pa,
                        "maxPressure": tab.max_pressure_pa,
                    }
                    for tab in spec.propellant.tabs
                ],
            },
            "grains": [
                {
                    "type": "BATES",
                    "properties": {
                        "diameter": grain.diameter_m,
                        "coreDiameter": grain.core_diameter_m,
                        "length": grain.length_m,
                        "inhibitedEnds": grain.inhibited_ends,
                    },
                }
                for grain in spec.grains
            ],
            "nozzle": {
                "throat": spec.nozzle.throat_diameter_m,
                "exit": spec.nozzle.exit_diameter_m,
                "throatLength": spec.nozzle.throat_length_m,
                "convAngle": spec.nozzle.conv_angle_deg,
                "divAngle": spec.nozzle.div_angle_deg,
                "efficiency": spec.nozzle.efficiency,
                "erosionCoeff": spec.nozzle.erosion_coeff,
                "slagCoeff": spec.nozzle.slag_coeff,
            },
            "config": {
                "ambPressure": spec.config.amb_pressure_pa,
                "burnoutThrustThres": spec.config.burnout_thrust_threshold_n,
                "burnoutWebThres": spec.config.burnout_web_threshold_m,
                "mapDim": spec.config.map_dim,
                "maxMassFlux": spec.config.max_mass_flux_kg_m2_s,
                "maxPressure": spec.config.max_pressure_pa,
                "minPortThroat": spec.config.min_port_throat_ratio,
                "timestep": spec.config.timestep_s,
            },
        }
        result = run_motor_first_design(
            motor_ric_path=None,
            motor_spec_payload=payload,
            objectives={"apogee_ft": 20000.0},
            constraints={
                "max_vehicle_length_in": 120.0,
                "max_vehicle_diameter_in": 6.0,
                "max_total_mass_lb": 200.0,
                "max_pressure_psi": 1000.0,
                "max_kn": 600.0,
            },
            design_space=None,
            output_dir="backend/tests",
            cd_max=0.5,
            mach_max=2.0,
            cd_ramp=False,
            tolerance_pct=0.05,
            ai_prompt=None,
        )
        self.assertIn("summary", result)
        self.assertIn("candidates", result)
        self.assertIn("ranked", result)
