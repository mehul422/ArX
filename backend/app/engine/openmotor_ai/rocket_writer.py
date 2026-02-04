from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import xml.etree.ElementTree as ET


DEFAULT_ORK_TEMPLATE = Path(__file__).resolve().parents[3] / "tests" / "testforai" / "rocket.ork"
DEFAULT_RKT_TEMPLATE = Path(__file__).resolve().parents[3] / "tests" / "33434.rkt"


@dataclass(frozen=True)
class RocketConfig:
    length_m: float
    diameter_m: float
    total_mass_kg: float
    motor_length_m: float | None = None
    ballast_mass_kg: float = 0.0
    stage_count: int = 1
    motor_designation: str | None = None
    motor_manufacturer: str | None = None
    motor_diameter_m: float | None = None


def _float_or_none(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(text)
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


def _scale_ork_lengths(root: ET.Element, target_length_m: float) -> None:
    stage_lengths = []
    for stage in root.iter("stage"):
        stage_lengths.append(_stage_primary_length(stage))
    current = max(stage_lengths or [0.0])
    if current <= 0 or target_length_m <= 0:
        return
    scale = target_length_m / current
    for stage in root.iter("stage"):
        subcomponents = stage.find("subcomponents")
        if subcomponents is None:
            continue
        for child in list(subcomponents):
            if child.tag not in ("nosecone", "bodytube", "transition"):
                continue
            length_node = child.find("length")
            value = _float_or_none(length_node.text if length_node is not None else None)
            if value is None:
                continue
            length_node.text = f"{value * scale}"


def _set_ork_radius(root: ET.Element, radius_m: float) -> None:
    if radius_m <= 0:
        return
    for comp in root.iter():
        if comp.tag not in ("nosecone", "bodytube", "transition"):
            continue
        for tag in ("radius", "outerradius", "aftradius"):
            node = comp.find(tag)
            if node is not None:
                node.text = f"{radius_m}"


def _first_bodytube_masscomponent(root: ET.Element) -> ET.Element | None:
    stage = root.find("./rocket/subcomponents/stage")
    if stage is None:
        return None
    bodytube = stage.find(".//bodytube")
    if bodytube is None:
        return None
    for node in bodytube.iter("masscomponent"):
        return node
    return None


def _set_ork_ballast_mass(root: ET.Element, mass_kg: float) -> None:
    if mass_kg <= 0:
        return
    mass_component = _first_bodytube_masscomponent(root)
    if mass_component is None:
        return
    mass_node = mass_component.find("mass")
    if mass_node is None:
        mass_node = ET.SubElement(mass_component, "mass")
    current = _float_or_none(mass_node.text) or 0.0
    mass_node.text = f"{current + max(mass_kg, 0.0)}"


def _set_ork_motor_mount_lengths(root: ET.Element, motor_length_m: float) -> None:
    if motor_length_m <= 0:
        return
    for innertube in root.iter("innertube"):
        if innertube.find("motormount") is None:
            continue
        length_node = innertube.find("length")
        if length_node is not None:
            length_node.text = f"{motor_length_m}"
        parent = None
        for candidate in root.iter("bodytube"):
            if innertube in list(candidate.iter("innertube")):
                parent = candidate
                break
        if parent is not None:
            parent_length = parent.find("length")
            if parent_length is not None:
                parent_length.text = f"{motor_length_m}"


def _relocate_stage_masscomponents(root: ET.Element) -> None:
    for stage in root.findall("./rocket/subcomponents/stage"):
        subcomponents = stage.find("subcomponents")
        if subcomponents is None:
            continue
        bodytube = stage.find(".//bodytube")
        if bodytube is None:
            continue
        tube_subs = bodytube.find("subcomponents")
        if tube_subs is None:
            tube_subs = ET.SubElement(bodytube, "subcomponents")
        for child in list(subcomponents):
            if child.tag != "masscomponent":
                continue
            subcomponents.remove(child)
            tube_subs.append(child)


def _set_ork_motor_fields(root: ET.Element, config: RocketConfig) -> None:
    if not config.motor_designation and not config.motor_manufacturer:
        return
    for motor in root.iter("motor"):
        if config.motor_manufacturer:
            manufacturer = motor.find("manufacturer")
            if manufacturer is None:
                manufacturer = ET.SubElement(motor, "manufacturer")
            manufacturer.text = config.motor_manufacturer
        if config.motor_designation:
            designation = motor.find("designation")
            if designation is None:
                designation = ET.SubElement(motor, "designation")
            designation.text = config.motor_designation
        if config.motor_diameter_m:
            diameter = motor.find("diameter")
            if diameter is None:
                diameter = ET.SubElement(motor, "diameter")
            diameter.text = f"{config.motor_diameter_m}"
        if config.motor_length_m:
            length = motor.find("length")
            if length is None:
                length = ET.SubElement(motor, "length")
            length.text = f"{config.motor_length_m}"


def _set_ork_ignition_events(root: ET.Element, stage_count: int) -> None:
    if stage_count < 2:
        return
    stages = root.findall("./rocket/subcomponents/stage")
    if len(stages) < 2:
        return
    sustainer = stages[0]
    booster = stages[-1]
    for stage, ignition_event in (
        (booster, "launch"),
        (sustainer, "burnout"),
    ):
        for motormount in stage.iter("motormount"):
            ign = motormount.find("ignitionevent")
            if ign is None:
                ign = ET.SubElement(motormount, "ignitionevent")
            ign.text = ignition_event
            delay = motormount.find("ignitiondelay")
            if delay is None:
                delay = ET.SubElement(motormount, "ignitiondelay")
            delay.text = "0.0"
            for cfg in motormount.findall("ignitionconfiguration"):
                cfg_ign = cfg.find("ignitionevent")
                if cfg_ign is None:
                    cfg_ign = ET.SubElement(cfg, "ignitionevent")
                cfg_ign.text = ignition_event
                cfg_delay = cfg.find("ignitiondelay")
                if cfg_delay is None:
                    cfg_delay = ET.SubElement(cfg, "ignitiondelay")
                cfg_delay.text = "0.0"


def _ensure_ork_two_stage(root: ET.Element) -> None:
    stages = root.findall("./rocket/subcomponents/stage")
    if len(stages) >= 2:
        return
    if not stages:
        return
    sustainer = stages[0]
    booster = ET.fromstring(ET.tostring(sustainer))
    name = booster.find("name")
    if name is None:
        name = ET.SubElement(booster, "name")
    name.text = "Booster"
    subs = booster.find("subcomponents")
    if subs is not None:
        for child in list(subs):
            if child.tag in ("nosecone", "parachute"):
                subs.remove(child)
            if child.tag == "masscomponent":
                subs.remove(child)
    root.find("./rocket/subcomponents").append(booster)


def write_ork(
    *,
    output_path: str,
    config: RocketConfig,
    template_path: str | None = None,
) -> str:
    template = Path(template_path) if template_path else DEFAULT_ORK_TEMPLATE
    if not template.exists():
        raise FileNotFoundError(f"ORK template not found: {template}")
    tree = ET.parse(template)
    root = tree.getroot()
    for parent in root.iter():
        for child in list(parent):
            if child.tag != "masscomponent":
                continue
            name = child.find("name")
            if name is not None and (name.text or "").strip() == "AI Ballast":
                parent.remove(child)
    _relocate_stage_masscomponents(root)
    if config.stage_count >= 2:
        _ensure_ork_two_stage(root)
    _scale_ork_lengths(root, config.length_m)
    _set_ork_radius(root, config.diameter_m / 2.0)
    if config.motor_length_m:
        _set_ork_motor_mount_lengths(root, config.motor_length_m)
    _set_ork_motor_fields(root, config)
    _set_ork_ignition_events(root, config.stage_count)
    _set_ork_ballast_mass(root, config.ballast_mass_kg)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output, encoding="utf-8", xml_declaration=True)
    return str(output)


def _scale_rkt_lengths(root: ET.Element, target_length_mm: float) -> None:
    if target_length_mm <= 0:
        return
    lengths: list[float] = []
    for part in root.iter():
        if part.tag not in ("NoseCone", "BodyTube", "Transition"):
            continue
        length_node = part.find("Len")
        value = _float_or_none(length_node.text if length_node is not None else None)
        if value is not None:
            lengths.append(value)
    current = sum(lengths)
    if current <= 0:
        return
    scale = target_length_mm / current
    for part in root.iter():
        if part.tag not in ("NoseCone", "BodyTube", "Transition"):
            continue
        length_node = part.find("Len")
        value = _float_or_none(length_node.text if length_node is not None else None)
        if value is None:
            continue
        length_node.text = f"{value * scale}"


def _set_rkt_diameter(root: ET.Element, diameter_mm: float) -> None:
    if diameter_mm <= 0:
        return
    for tag in ("OD", "BaseDia", "MotorDia"):
        for node in root.iter(tag):
            node.text = f"{diameter_mm}"


def _sum_rkt_known_mass(root: ET.Element) -> float:
    total = 0.0
    for node in root.iter("KnownMass"):
        value = _float_or_none(node.text)
        if value is not None:
            total += value
    return total


def _ensure_rkt_ballast(root: ET.Element) -> ET.Element:
    for node in root.iter("MassObject"):
        name = node.find("Name")
        if name is not None and (name.text or "").strip() == "AI Ballast":
            return node
    stage = root.find(".//Stage3Parts")
    if stage is None:
        raise ValueError("RKT template missing Stage3Parts")
    ballast = ET.SubElement(stage, "MassObject")
    name = ET.SubElement(ballast, "Name")
    name.text = "AI Ballast"
    known_mass = ET.SubElement(ballast, "KnownMass")
    known_mass.text = "0.0"
    return ballast


def _set_rkt_ballast_mass(root: ET.Element, mass_g: float) -> None:
    ballast = _ensure_rkt_ballast(root)
    known_mass = ballast.find("KnownMass")
    if known_mass is None:
        known_mass = ET.SubElement(ballast, "KnownMass")
    known_mass.text = f"{max(mass_g, 0.0)}"


def write_rkt(
    *,
    output_path: str,
    config: RocketConfig,
    template_path: str | None = None,
) -> str:
    template = Path(template_path) if template_path else DEFAULT_RKT_TEMPLATE
    if not template.exists():
        raise FileNotFoundError(f"RKT template not found: {template}")
    tree = ET.parse(template)
    root = tree.getroot()
    target_length_mm = config.length_m * 1000.0
    _scale_rkt_lengths(root, target_length_mm)
    _set_rkt_diameter(root, config.diameter_m * 1000.0)
    total_known_g = _sum_rkt_known_mass(root)
    target_g = max(config.total_mass_kg, 0.0) * 1000.0
    ballast_g = max(0.0, target_g - total_known_g)
    _set_rkt_ballast_mass(root, ballast_g)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    tree.write(output, encoding="utf-8", xml_declaration=True)
    return str(output)
