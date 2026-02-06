from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import zipfile
import xml.etree.ElementTree as ET

from app.engine.openmotor_ai.rocket_writer import RocketConfig, write_rkt
from app.engine.openrocket.runner import run_openrocket_core_masscalc, run_openrocket_geometry


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


_EXTERNAL_TAGS = {"nosecone", "bodytube", "transition"}
_INTERNAL_TAGS = {
    "innertube",
    "motorblock",
    "engineblock",
    "bulkhead",
    "masscomponent",
    "parachute",
    "shockcord",
    "coupler",
    "launchlug",
    "railbutton",
    "trapezoidfinset",
    "ellipticalfinset",
    "freeformfinset",
}


def _load_ork_root(ork_path: str) -> ET.Element:
    if zipfile.is_zipfile(ork_path):
        with zipfile.ZipFile(ork_path, "r") as zf:
            ork_entry = next((name for name in zf.namelist() if name.endswith(".ork")), None)
            if not ork_entry:
                raise ValueError("ORK archive missing .ork XML")
            xml_bytes = zf.read(ork_entry)
        return ET.fromstring(xml_bytes)
    tree = ET.parse(ork_path)
    return tree.getroot()


def calculate_stack_length_m(ork_path: str) -> float:
    """
    Parses an OpenRocket file to calculate the total length of the stack.
    Logic: Sums 'Exposed Lengths' of NoseCones, BodyTubes, and Transitions.
    """
    # --- STEP 1: LOAD THE XML ---
    tree = None
    if zipfile.is_zipfile(ork_path):
        try:
            with zipfile.ZipFile(ork_path, "r") as zf:
                xml_filename = next(
                    (
                        name
                        for name in zf.namelist()
                        if name.endswith(".ork") or name.endswith(".xml")
                    ),
                    None,
                )
                if xml_filename:
                    with zf.open(xml_filename) as handle:
                        tree = ET.parse(handle)
        except Exception as exc:
            raise ValueError(f"Error reading ZIP: {exc}") from exc
    if tree is None:
        try:
            tree = ET.parse(ork_path)
        except ET.ParseError as exc:
            raise ValueError("Error: File is not valid XML or ORK.") from exc

    root = tree.getroot()
    # --- STEP 2: LOCATE STAGES ---
    rocket = root.find("rocket")
    if rocket is None:
        raise ValueError("Error: No <rocket> root found.")
    main_subs = rocket.find("subcomponents")
    if main_subs is None:
        return 0.0
    stages = main_subs.findall("stage")
    total_stack_length = 0.0

    # --- STEP 3: ITERATE STAGES ---
    for stage in stages:
        stage_subcomponents = stage.find("subcomponents")
        if stage_subcomponents is None:
            continue
        stage_len = 0.0

        # --- STEP 4: ITERATE COMPONENTS (Direct Child Iteration) ---
        for component in stage_subcomponents:
            tag = component.tag.lower()
            if tag in ["nosecone", "bodytube", "transition"]:
                # --- STEP 5: GET RAW LENGTH ---
                len_node = component.find("length")
                if len_node is None:
                    len_node = component.find("len")
                raw_len = float(len_node.text) if len_node is not None else 0.0

                # --- STEP 6: SUBTRACT SHOULDERS ---
                shoulder_deduction = 0.0
                for child in component:
                    if "shoulder" in child.tag.lower():
                        s_len_node = child.find("length") or child.find("len")
                        if s_len_node is not None:
                            shoulder_deduction = float(s_len_node.text)
                aft_s = component.find("aftshoulderlength")
                if aft_s is not None:
                    shoulder_deduction = max(
                        shoulder_deduction, float(aft_s.text)
                    )
                exposed_len = max(0.0, raw_len - shoulder_deduction)
                stage_len += exposed_len

        total_stack_length += stage_len

    return total_stack_length


def _exposed_length_m(node: ET.Element) -> float:
    length = _float_or_none(node.findtext("length")) or 0.0
    if node.tag == "nosecone":
        shoulder = _float_or_none(node.findtext("aftshoulderlength")) or 0.0
        return max(0.0, length - shoulder)
    if node.tag == "transition":
        aft = _float_or_none(node.findtext("aftshoulderlength")) or 0.0
        fore = _float_or_none(node.findtext("foreshoulderlength")) or 0.0
        return max(0.0, length - aft - fore)
    if node.tag == "bodytube":
        return max(0.0, length)
    return max(0.0, length)


def _component_radius_m(node: ET.Element) -> float:
    radius = 0.0
    for tag in ("radius", "outerradius", "aftradius"):
        value = _float_or_none(node.findtext(tag))
        if value is not None:
            radius = max(radius, value)
    return radius


def _component_start_m(node: ET.Element, parent_start: float, parent_length: float) -> float:
    axial = node.find("axialoffset")
    position = node.find("position")
    if position is None or position.text is None:
        return parent_start
    method = None
    if axial is not None:
        method = axial.get("method")
    if not method and position is not None:
        method = position.get("type")
    try:
        value = float(position.text)
    except Exception:
        value = 0.0
    if method == "absolute":
        return value
    if method == "bottom":
        return parent_start + parent_length + value
    return parent_start + value


def _walk_components(
    node: ET.Element,
    parent_start: float,
    parent_length: float,
    bounds: list[tuple[float, float]],
    radii: list[float],
) -> None:
    tag = node.tag
    start = parent_start
    if tag != "rocket":
        start = _component_start_m(node, parent_start, parent_length)
    length = _exposed_length_m(node) if tag in _EXTERNAL_TAGS else 0.0
    if tag in _EXTERNAL_TAGS:
        bounds.append((start, start + length))
        radius = _component_radius_m(node)
        if radius > 0:
            radii.append(radius)

    next_parent_start = start
    next_parent_length = length if tag in _EXTERNAL_TAGS else 0.0

    subcomponents = node.find("subcomponents")
    if subcomponents is None:
        return
    for child in list(subcomponents):
        if child.tag in _INTERNAL_TAGS:
            continue
        _walk_components(child, next_parent_start, next_parent_length, bounds, radii)


def _extract_geometry(ork_path: str) -> OrkGeometry:
    length_m = calculate_stack_length_m(ork_path)
    try:
        geometry = run_openrocket_geometry({"rocket_path": ork_path})
        diameter_m = float(geometry.get("diameter_m") or 0.0)
        if length_m > 0 and diameter_m > 0:
            return OrkGeometry(length_m=length_m, diameter_m=diameter_m)
    except Exception:
        diameter_m = 0.0
    root = _load_ork_root(ork_path)
    rocket = root.find("rocket")
    if rocket is None:
        raise ValueError("ORK missing rocket root")
    bounds: list[tuple[float, float]] = []
    radii: list[float] = []
    _walk_components(rocket, parent_start=0.0, parent_length=0.0, bounds=bounds, radii=radii)
    if not bounds or not radii:
        raise ValueError("Failed to infer ORK geometry")
    if length_m <= 0:
        length_m = max(end for _, end in bounds) - min(start for start, _ in bounds)
    radius_m = max(radii)
    if length_m <= 0 or radius_m <= 0:
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
