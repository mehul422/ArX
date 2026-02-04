from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import xml.etree.ElementTree as ET

from app.engine.openmotor_ai.rocket_writer import RocketConfig, write_rkt
from app.engine.openrocket.runner import run_openrocket_core_masscalc


@dataclass(frozen=True)
class OrkGeometry:
    length_m: float
    diameter_m: float


def _float_or_none(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _stage_primary_length(stage: ET.Element) -> float:
    total = 0.0
    subcomponents = stage.find("subcomponents")
    if subcomponents is None:
        return total
    for child in list(subcomponents):
        if child.tag not in ("nosecone", "bodytube", "transition"):
            continue
        length_node = child.find("length")
        value = _float_or_none(length_node.text if length_node is not None else None)
        if value is not None:
            total += value
    return total


def _stage_radius_m(stage: ET.Element) -> float | None:
    for comp in stage.iter():
        if comp.tag not in ("nosecone", "bodytube", "transition"):
            continue
        for tag in ("radius", "outerradius", "aftradius"):
            node = comp.find(tag)
            value = _float_or_none(node.text if node is not None else None)
            if value:
                return value
    return None


def _extract_geometry(ork_path: str) -> OrkGeometry:
    tree = ET.parse(ork_path)
    root = tree.getroot()
    stages = root.findall("./rocket/subcomponents/stage")
    if not stages:
        raise ValueError("ORK missing stage definitions")
    stage_lengths = [_stage_primary_length(stage) for stage in stages]
    length_m = max(stage_lengths or [0.0])
    radius_m = _stage_radius_m(stages[0]) or _stage_radius_m(stages[-1])
    if length_m <= 0 or not radius_m:
        raise ValueError("Failed to infer ORK geometry")
    return OrkGeometry(length_m=length_m, diameter_m=radius_m * 2.0)


def ork_to_rkt(
    *,
    ork_path: str,
    eng_path: str | None,
    output_dir: str,
    rkt_filename: str | None = None,
) -> dict[str, object]:
    geometry = _extract_geometry(ork_path)
    mass_params = {
        "rocket_path": ork_path,
        "motor_path": eng_path,
    }
    mass_result = run_openrocket_core_masscalc(mass_params)
    mass_kg = float(mass_result.get("mass_kg") or 0.0)
    if mass_kg <= 0:
        raise ValueError("Invalid mass from OpenRocket")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rkt_name = rkt_filename or "integrated.rkt"
    rkt_path = out_dir / rkt_name
    write_rkt(
        output_path=str(rkt_path),
        config=RocketConfig(
            length_m=geometry.length_m,
            diameter_m=geometry.diameter_m,
            total_mass_kg=mass_kg,
            ballast_mass_kg=0.0,
        ),
    )

    manifest = {
        "ork_path": ork_path,
        "rkt_path": str(rkt_path),
        "eng_path": eng_path,
        "length_m": geometry.length_m,
        "diameter_m": geometry.diameter_m,
        "mass_kg": mass_kg,
    }
    manifest_path = out_dir / "integration_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "ork_path": ork_path,
        "rkt_path": str(rkt_path),
        "eng_path": eng_path,
        "manifest_path": str(manifest_path),
        "length_m": geometry.length_m,
        "diameter_m": geometry.diameter_m,
        "mass_kg": mass_kg,
    }
