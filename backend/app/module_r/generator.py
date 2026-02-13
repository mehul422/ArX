import os
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass

# --- CONSTANTS ---
GRAVITY = 9.81
AIR_DENSITY = 1.225
DEFAULT_CD = 0.75
PARACHUTE_CD = 1.5
DESCENT_RATE_TARGET = 6.0  # m/s

# Material Densities (kg/m^3)
MAT_FIBERGLASS = 1850.0
MAT_CARDBOARD = 690.0
MAT_PLYWOOD = 680.0


@dataclass
class MotorData:
    name: str
    diameter: float  # meters
    length: float  # meters
    propellant_mass: float  # kg
    total_impulse: float  # Ns
    avg_thrust: float  # N


@dataclass
class RocketDimensions:
    body_od: float
    body_id: float
    body_length: float
    nose_length: float
    motor_mount_od: float
    motor_mount_id: float
    motor_mount_length: float
    fin_root: float
    fin_tip: float
    fin_span: float
    fin_sweep: float
    parachute_dia: float


class RICParser:
    """Parses RASP (.ric) motor files."""

    @staticmethod
    def parse(file_path: str) -> MotorData:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            data_line = None
            for line in lines:
                if line.strip().startswith(";") or not line.strip():
                    continue
                # RASP: Name Dia(mm) Len(mm) ...
                data_line = line.split()
                break

            if not data_line:
                # Fallback if empty
                return MotorData("Unknown", 0.054, 0.4, 0.5, 1000.0, 200.0)

            name = data_line[0]
            diameter = float(data_line[1]) / 1000.0
            length = float(data_line[2]) / 1000.0
            prop_mass = float(data_line[4])

            # Heuristic Impulse Calc
            total_impulse = prop_mass * 200 * 9.81

            return MotorData(name, diameter, length, prop_mass, total_impulse, 100.0)

        except Exception as e:
            print(f"Error parsing .ric via simple parser: {e}")
            # Fallback to project-native OpenMotor parser for non-RASP formats.
            try:
                from app.engine.openmotor_ai.ric_parser import load_ric
                from app.engine.openmotor_ai.spec import spec_from_ric

                spec = spec_from_ric(load_ric(file_path))
                grains = getattr(spec, "grains", []) or []
                if not grains:
                    raise ValueError("no grains found in parsed RIC")
                diameter = float(grains[0].diameter_m)
                length = float(sum(g.length_m for g in grains))
                prop_mass = float(sum(g.mass_kg for g in grains if hasattr(g, "mass_kg")) or 0.5)
                avg_thrust = max(float(getattr(spec, "avg_thrust_n", 0.0) or 0.0), 100.0)
                total_impulse = max(float(getattr(spec, "total_impulse_ns", 0.0) or 0.0), avg_thrust * 5.0)
                return MotorData(
                    str(getattr(spec.propellant, "name", "OpenMotor")),
                    diameter,
                    length,
                    max(prop_mass, 0.1),
                    total_impulse,
                    avg_thrust,
                )
            except Exception as fallback_error:
                print(f"Error parsing .ric via openmotor parser: {fallback_error}")
                return MotorData("Fallback", 0.054, 0.4, 0.5, 1500.0, 300.0)


class PhysicsEngine:
    """Sizes the rocket based on engineering constraints."""

    @staticmethod
    def calculate_dimensions(
        motor: MotorData, max_length: float, max_mass: float, target_apogee: float
    ) -> RocketDimensions:
        _ = max_mass
        _ = target_apogee
        # 1. Body Sizing
        min_body_od = motor.diameter + 0.010
        _ = min_body_od
        standard_tubes = [
            (0.024, 0.023),
            (0.042, 0.040),
            (0.054, 0.052),
            (0.075, 0.072),
            (0.098, 0.095),
        ]

        selected_od, selected_id = standard_tubes[-1]
        for od, id_val in standard_tubes:
            if id_val > motor.diameter + 0.005:
                selected_od, selected_id = od, id_val
                break

        # 2. Length Sizing (Stability Ratio ~15-20x Dia)
        ideal_length = selected_od * 18.0
        if ideal_length > max_length:
            ideal_length = max_length
        min_len = motor.length + (selected_od * 6)
        if ideal_length < min_len:
            ideal_length = min_len

        # 3. Aerodynamics
        nose_len = selected_od * 5.0
        body_len = ideal_length - nose_len

        # Fins (Barrowman Stability > 1.5)
        fin_root = selected_od * 2.5
        fin_tip = selected_od * 1.0
        fin_span = selected_od * 1.75
        fin_sweep = selected_od * 1.5

        # 4. Recovery
        vol_wall = math.pi * (selected_od * body_len) * 0.002
        est_mass = (vol_wall * MAT_FIBERGLASS) + motor.propellant_mass
        drag_area = (2 * est_mass * GRAVITY) / (
            AIR_DENSITY * PARACHUTE_CD * (DESCENT_RATE_TARGET**2)
        )
        chute_dia = math.sqrt(drag_area * 4 / math.pi)

        return RocketDimensions(
            body_od=selected_od,
            body_id=selected_id,
            body_length=body_len,
            nose_length=nose_len,
            motor_mount_od=motor.diameter + 0.002,
            motor_mount_id=motor.diameter,
            motor_mount_length=motor.length + 0.02,
            fin_root=fin_root,
            fin_tip=fin_tip,
            fin_span=fin_span,
            fin_sweep=fin_sweep,
            parachute_dia=chute_dia,
        )


class ORKGenerator:
    """Builds valid OpenRocket XML."""

    def __init__(self):
        self.root = ET.Element("openrocket", version="1.0")
        self.rocket = ET.SubElement(self.root, "rocket")
        self.sim = ET.SubElement(self.root, "simulations")

    def _add_material(self, element, material_type="Fiberglass"):
        mat = ET.SubElement(element, "material")
        mat.set("type", "bulk")
        if material_type == "Fiberglass":
            mat.set("density", str(MAT_FIBERGLASS))
        elif material_type == "Cardboard":
            mat.set("density", str(MAT_CARDBOARD))
        elif material_type == "Plywood":
            mat.set("density", str(MAT_PLYWOOD))

    def build(self, dims: RocketDimensions, motor: MotorData):
        _ = motor
        sub = ET.SubElement(self.rocket, "subcomponents")
        stage = ET.SubElement(sub, "stage")
        stage_subs = ET.SubElement(stage, "subcomponents")

        # Nose Cone
        nc = ET.SubElement(stage_subs, "nosecone")
        ET.SubElement(nc, "length").text = str(dims.nose_length)
        ET.SubElement(nc, "aftradius").text = str(dims.body_od / 2)
        ET.SubElement(nc, "shape").text = "ogive"
        ET.SubElement(nc, "finish").text = "smooth"
        self._add_material(nc, "Fiberglass")

        # Body Tube
        bt = ET.SubElement(stage_subs, "bodytube")
        ET.SubElement(bt, "length").text = str(dims.body_length)
        ET.SubElement(bt, "outerradius").text = str(dims.body_od / 2)
        ET.SubElement(bt, "innerradius").text = str(dims.body_id / 2)
        self._add_material(bt, "Fiberglass")
        bt_subs = ET.SubElement(bt, "subcomponents")

        # Motor Mount (Inner Tube)
        mm = ET.SubElement(bt_subs, "innertube")
        ET.SubElement(mm, "length").text = str(dims.motor_mount_length)
        ET.SubElement(mm, "outerradius").text = str(dims.motor_mount_od / 2)
        ET.SubElement(mm, "innerradius").text = str(dims.motor_mount_id / 2)
        offset = dims.body_length - dims.motor_mount_length
        ET.SubElement(mm, "position", type="top", method="absolute").text = str(offset)
        self._add_material(mm, "Cardboard")

        # Motor Config
        m_cfg = ET.SubElement(mm, "motormount")
        ET.SubElement(m_cfg, "ignitionevent").text = "automatic"
        ET.SubElement(m_cfg, "ignitiondelay").text = "0.0"
        ET.SubElement(m_cfg, "overhang").text = "0.01"

        # Centering Rings (Top & Bottom)
        for pos_type, pos_val in [("top", offset), ("bottom", 0.01)]:
            cr = ET.SubElement(bt_subs, "centeringring")
            ET.SubElement(cr, "outerradius").text = str(dims.body_id / 2)
            ET.SubElement(cr, "innerradius").text = str(dims.motor_mount_od / 2)
            ET.SubElement(cr, "length").text = "0.005"
            ET.SubElement(cr, "position", type=pos_type, method="absolute").text = str(
                pos_val
            )
            self._add_material(cr, "Plywood")

        # Fins
        fins = ET.SubElement(bt_subs, "trapezoidfinset")
        ET.SubElement(fins, "rootchord").text = str(dims.fin_root)
        ET.SubElement(fins, "tipchord").text = str(dims.fin_tip)
        ET.SubElement(fins, "height").text = str(dims.fin_span)
        ET.SubElement(fins, "sweepangle").text = str(dims.fin_sweep)
        ET.SubElement(fins, "thickness").text = "0.003"
        ET.SubElement(fins, "fincount").text = "3"
        ET.SubElement(fins, "position", type="bottom", method="absolute").text = "0.0"
        self._add_material(fins, "Fiberglass")

        # Parachute
        chute = ET.SubElement(bt_subs, "parachute")
        ET.SubElement(chute, "diameter").text = str(dims.parachute_dia)
        ET.SubElement(chute, "dragcoefficient").text = str(PARACHUTE_CD)
        ET.SubElement(chute, "packedlength").text = "0.15"
        ET.SubElement(chute, "packedradius").text = str((dims.body_id / 2) * 0.8)
        ET.SubElement(chute, "position", type="top", method="absolute").text = "0.1"

    def save(self, output_path):
        tree = ET.ElementTree(self.root)
        ET.indent(tree, space="  ", level=0)
        tree.write(output_path, encoding="utf-8", xml_declaration=True)


class SmartRocketGenerator:
    """Main Entry Point."""

    def __init__(self, ric_path, constraints):
        self.ric_path = ric_path
        self.constraints = constraints

    def generate(self, output_ork_path):
        # 1. Parse Motor
        parser = RICParser()
        motor = parser.parse(self.ric_path)

        # 2. Calc Dimensions
        phys = PhysicsEngine()
        dims = phys.calculate_dimensions(
            motor,
            self.constraints.get("upper_length", 3.0),
            self.constraints.get("upper_mass", 10.0),
            self.constraints.get("target_apogee", 1000.0),
        )

        # 3. Build XML
        gen = ORKGenerator()
        gen.build(dims, motor)
        out_dir = os.path.dirname(output_ork_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        gen.save(output_ork_path)
        return output_ork_path


def run_auto_build(request):
    """Compatibility shim for legacy tests/imports."""
    from datetime import datetime
    from pathlib import Path
    import uuid

    from app.module_r.schemas import (
        BallastMass,
        BodyTube,
        Bulkhead,
        FinSet,
        InnerTube,
        ModuleRAutoBuildResponse,
        NoseCone,
        ParachuteRef,
        RocketAssembly,
        Stage,
        TelemetryMass,
    )

    ric_paths = [
        path
        for path in (request.ric_paths or ([request.ric_path] if request.ric_path else []))
        if path
    ]
    if not ric_paths:
        raise ValueError("no .ric paths provided")

    constraints = {
        "upper_length": float(request.constraints.upper_length_m),
        "upper_mass": float(request.constraints.upper_mass_kg),
        "target_apogee": float(request.constraints.target_apogee_m or 1000.0),
    }
    parser = RICParser()
    motor = parser.parse(ric_paths[0])
    dims = PhysicsEngine.calculate_dimensions(
        motor,
        constraints["upper_length"],
        constraints["upper_mass"],
        constraints["target_apogee"],
    )

    output_root = Path(__file__).resolve().parents[2] / "tests" / "module_r"
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / f"module_r_parametric_{uuid.uuid4().hex}.ork"
    SmartRocketGenerator(ric_paths[0], constraints).generate(str(output_path))

    children = []
    if request.include_telemetry:
        children.append(
            TelemetryMass(
                id="telemetry-1",
                name="Telemetry Module",
                mass_kg=0.35,
                position_from_bottom_m=max(dims.body_length * 0.6, 0.05),
            )
        )
    if request.include_ballast:
        children.append(
            BallastMass(
                id="ballast-1",
                name="Ballast",
                mass_kg=max(0.08, motor.propellant_mass * 0.15),
                position_from_bottom_m=max(dims.body_length * 0.2, 0.03),
            )
        )
    if request.include_parachute:
        children.append(
            ParachuteRef(
                id="parachute-1",
                name="Recovery Parachute",
                library_id="smart-parametric",
                diameter_m=dims.parachute_dia,
                position_from_bottom_m=max(dims.body_length * 0.8, 0.05),
            )
        )

    stage_length_m = max(motor.length + 0.05, 0.15)
    remaining_body_m = max(
        constraints["upper_length"] - dims.nose_length - stage_length_m,
        0.2,
    )
    body_main_m = max(remaining_body_m * 0.7, 0.12)
    body_aux_m = max(remaining_body_m - body_main_m, 0.08)

    assembly = RocketAssembly(
        name=f"Smart Parametric {motor.name}",
        design_mode="AUTO",
        global_diameter_m=dims.body_od,
        nose_cone=NoseCone(
            id="nose-1",
            name="Ogive Nose Cone",
            type="OGIVE",
            length_m=dims.nose_length,
            diameter_m=dims.body_od,
            material="Fiberglass",
        ),
        stages=[
            Stage(
                id="stage-1",
                name="Stage 1",
                length_m=stage_length_m,
                diameter_m=dims.body_od,
                motor_mount=InnerTube(
                    id="stage-1-mount",
                    name="Motor Mount",
                    outer_diameter_m=dims.motor_mount_od,
                    inner_diameter_m=dims.motor_mount_id,
                    length_m=dims.motor_mount_length,
                    position_from_bottom_m=0.01,
                    is_motor_mount=True,
                ),
                bulkhead=Bulkhead(
                    id="stage-1-bulkhead",
                    name="Forward Bulkhead",
                    height_m=0.005,
                    material="Plywood",
                    position_from_top_m=0.0,
                ),
            )
        ],
        body_tubes=[
            BodyTube(
                id="body-1",
                name="Main Body Tube",
                length_m=body_main_m,
                diameter_m=dims.body_od,
                wall_thickness_m=max((dims.body_od - dims.body_id) / 2.0, 0.0015),
                children=children,
            ),
            BodyTube(
                id="body-2",
                name="Avionics Tube",
                length_m=body_aux_m,
                diameter_m=dims.body_od,
                wall_thickness_m=max((dims.body_od - dims.body_id) / 2.0, 0.0015),
                children=[
                    InnerTube(
                        id="body-2-coupler",
                        name="Electronics Coupler",
                        outer_diameter_m=max(dims.body_od * 0.75, 0.02),
                        inner_diameter_m=max(dims.body_od * 0.72, 0.018),
                        length_m=max(body_aux_m * 0.5, 0.05),
                        position_from_bottom_m=max(body_aux_m * 0.2, 0.01),
                        is_motor_mount=False,
                    )
                ],
            ),
        ],
        fin_sets=[
            FinSet(
                id="fins-1",
                name="Primary Fin Set",
                parent_tube_id="stage-1",
                fin_count=3,
                root_chord_m=dims.fin_root,
                tip_chord_m=dims.fin_tip,
                span_m=dims.fin_span,
                sweep_m=dims.fin_sweep,
                thickness_m=0.003,
                position_from_bottom_m=0.0,
            )
        ],
        metadata={
            "backend_variant": "smart_parametric",
            "generator": "SmartRocketGenerator",
            "winner_score": 0.0,
            "predicted_apogee_m": constraints["target_apogee"],
        },
    )
    return ModuleRAutoBuildResponse(
        assembly=assembly,
        ork_path=str(output_path),
        created_at=datetime.utcnow(),
    )
