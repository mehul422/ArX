from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from app.module_r.schemas import BodyTube, FinSet, NoseCone, RocketAssembly


@dataclass
class OrkParseResult:
    assembly: RocketAssembly
    warnings: list[str]


def _to_float(value: str | None, fallback: float = 0.0) -> float:
    if value is None:
        return fallback
    try:
        return float(value)
    except Exception:
        return fallback


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[-1].lower()


def _load_ork_root(path: str) -> ET.Element:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path, "r") as zf:
            entry = next((name for name in zf.namelist() if name.lower().endswith((".ork", ".xml"))), None)
            if not entry:
                raise ValueError("ORK archive does not contain XML content")
            return ET.fromstring(zf.read(entry))
    return ET.parse(path).getroot()


def parse_ork_to_assembly(path: str) -> OrkParseResult:
    root = _load_ork_root(path)
    warnings: list[str] = []

    nose: NoseCone | None = None
    body_tubes: list[BodyTube] = []
    fin_sets: list[FinSet] = []

    for node in root.iter():
        tag = _local_name(node.tag)
        if tag == "nosecone" and nose is None:
            length_m = _to_float(node.findtext("length"), 0.2)
            radius_m = max(_to_float(node.findtext("aftradius"), 0.025), 0.005)
            shape = str(node.findtext("shape") or "ogive").upper()
            cone_type = "OGIVE"
            if "CONICAL" in shape or shape == "CONE":
                cone_type = "CONICAL"
            elif "ELLIP" in shape:
                cone_type = "ELLIPTICAL"
            elif "PARAB" in shape:
                cone_type = "PARABOLIC"
            nose = NoseCone(
                id="ork-nose-1",
                name="Imported Nose Cone",
                type=cone_type,  # type: ignore[arg-type]
                length_m=max(length_m, 0.01),
                diameter_m=radius_m * 2.0,
                material="Fiberglass",
            )
            continue

        if tag == "bodytube":
            length_m = max(_to_float(node.findtext("length"), 0.2), 0.01)
            radius_outer = max(_to_float(node.findtext("outerradius"), 0.025), 0.005)
            inner_radius = max(_to_float(node.findtext("innerradius"), radius_outer - 0.002), 0.0)
            wall = max(radius_outer - inner_radius, 0.0005)
            body_tubes.append(
                BodyTube(
                    id=f"ork-body-{len(body_tubes) + 1}",
                    name=f"Imported Body Tube {len(body_tubes) + 1}",
                    length_m=length_m,
                    diameter_m=radius_outer * 2.0,
                    wall_thickness_m=wall,
                    children=[],
                )
            )
            continue

        if tag == "trapezoidfinset":
            fin_sets.append(
                FinSet(
                    id=f"ork-fin-{len(fin_sets) + 1}",
                    name=f"Imported Fin Set {len(fin_sets) + 1}",
                    parent_tube_id="ork-body-1",
                    fin_count=max(int(_to_float(node.findtext("fincount"), 3)), 1),
                    root_chord_m=max(_to_float(node.findtext("rootchord"), 0.08), 0.01),
                    tip_chord_m=max(_to_float(node.findtext("tipchord"), 0.04), 0.005),
                    span_m=max(_to_float(node.findtext("height"), 0.05), 0.005),
                    sweep_m=max(_to_float(node.findtext("sweep"), _to_float(node.findtext("sweepangle"), 0.0)), 0.0),
                    thickness_m=max(_to_float(node.findtext("thickness"), 0.003), 0.0005),
                    position_from_bottom_m=max(_to_float(node.findtext("position"), 0.0), 0.0),
                )
            )

    if nose is None:
        warnings.append("Nose cone not found in ORK; applied fallback nose.")
        nose = NoseCone(
            id="ork-nose-fallback",
            name="Fallback Nose Cone",
            type="OGIVE",
            length_m=0.2,
            diameter_m=0.05,
            material="Fiberglass",
        )
    if not body_tubes:
        warnings.append("Body tubes not found in ORK; applied fallback body.")
        body_tubes = [
            BodyTube(
                id="ork-body-fallback",
                name="Fallback Body Tube",
                length_m=0.6,
                diameter_m=nose.diameter_m,
                wall_thickness_m=0.002,
                children=[],
            )
        ]
    if not fin_sets:
        warnings.append("Fin sets not found in ORK; applied fallback fin set.")
        fin_sets = [
            FinSet(
                id="ork-fin-fallback",
                name="Fallback Fin Set",
                parent_tube_id=body_tubes[0].id,
                fin_count=3,
                root_chord_m=0.08,
                tip_chord_m=0.04,
                span_m=0.05,
                sweep_m=0.01,
                thickness_m=0.003,
                position_from_bottom_m=0.0,
            )
        ]

    global_diameter = max([nose.diameter_m] + [tube.diameter_m for tube in body_tubes])
    for tube in body_tubes:
        tube.diameter_m = global_diameter
    nose.diameter_m = global_diameter

    assembly = RocketAssembly(
        name=f"Imported ORK {Path(path).name}",
        design_mode="MANUAL",
        global_diameter_m=global_diameter,
        nose_cone=nose,
        stages=[],
        body_tubes=body_tubes,
        fin_sets=fin_sets,
        metadata={"source": "ork_parser"},
    )
    return OrkParseResult(assembly=assembly, warnings=warnings)
