from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jpype

from app.engine.openrocket.runner import (
    ensure_openrocket_initialized,
    save_openrocket_document,
)
# Ensure your schemas.py actually has these definitions
from app.module_r.schemas import (
    BallastMass,
    BodyTube,
    Bulkhead,
    FinSet,
    InnerTube,
    ParachuteRef,
    RocketAssembly,
    Stage,
    TelemetryMass,
)


def _clip(value: float, low: float, high: float) -> float:
    if high < low:
        return low
    if value < low:
        return low
    if value > high:
        return high
    return value


def _safe_set(obj: Any, method: str, value: Any, convert_type: type = None) -> bool:
    """Helper to call a method via reflection if it exists, handling type conversion."""
    if not hasattr(obj, method):
        return False
    try:
        val = convert_type(value) if convert_type else value
        getattr(obj, method)(val)
        return True
    except Exception:
        return False


def _set_coordinate(component: Any, location_m: float) -> None:
    """Sets the position of a component relative to the top of its parent."""
    _safe_set(component, "setAxialOffset", location_m, float)


def _set_position_from_bottom(component: Any, location_m: float) -> None:
    try:
        AxialPosition = jpype.JClass(
            "net.sf.openrocket.rocketcomponent.position.AxialPosition$Position"
        )
        if hasattr(component, "setPosition"):
            component.setPosition(AxialPosition.BOTTOM)
    except Exception:
        pass
    _safe_set(component, "setAxialOffset", location_m, float)


def _set_position_from_top(component: Any, location_m: float) -> None:
    try:
        AxialPosition = jpype.JClass(
            "net.sf.openrocket.rocketcomponent.position.AxialPosition$Position"
        )
        if hasattr(component, "setPosition"):
            component.setPosition(AxialPosition.TOP)
    except Exception:
        pass
    _safe_set(component, "setAxialOffset", location_m, float)


def _material_density_guess(name: str) -> float:
    key = (name or "").strip().lower()
    if "carbon" in key:
        return 1780.0
    if "fiberglass" in key:
        return 1850.0
    if "phenolic" in key:
        return 950.0
    if "aluminum" in key:
        return 2700.0
    if "steel" in key:
        return 7850.0
    if "nylon" in key:
        return 1150.0
    if "blue tube" in key:
        return 780.0
    return 700.0  # cardboard default


def _apply_material(component: Any, material_name: str | None, material_type: str = "bulk") -> None:
    if not material_name:
        return
    # First try direct name setter when available.
    if _safe_set(component, "setMaterialName", material_name):
        return
    try:
        Databases = jpype.JClass("net.sf.openrocket.database.Databases")
        Material = jpype.JClass("net.sf.openrocket.material.Material")
        MatType = jpype.JClass("net.sf.openrocket.material.Material$Type")
        mat_kind = MatType.SURFACE if material_type == "surface" else MatType.BULK
        density = _material_density_guess(material_name)
        # OpenRocket APIs differ by version; try common overloads.
        material_obj = None
        try:
            material_obj = Databases.findMaterial(mat_kind, material_name, float(density))
        except Exception:
            try:
                material_obj = Databases.findMaterial(material_name, float(density), mat_kind)
            except Exception:
                material_obj = None
        if material_obj is not None:
            _safe_set(component, "setMaterial", material_obj)
    except Exception:
        # Material assignment is best-effort, keep export resilient.
        pass


def _set_mass_component_type(mass_obj: Any, preferred: str) -> None:
    try:
        MassType = jpype.JClass(
            "net.sf.openrocket.rocketcomponent.MassComponent$MassComponentType"
        )
    except Exception:
        return
    enum_candidates = {
        "flightcomputer": ("FLIGHTCOMPUTER",),
        "masscomponent": ("MASSCOMPONENT", "MASS_COMPONENT"),
    }.get(preferred.lower(), ())
    for enum_name in enum_candidates:
        if hasattr(MassType, enum_name) and _safe_set(
            mass_obj,
            "setMassComponentType",
            getattr(MassType, enum_name),
        ):
            return


def _is_payload_named(name: str | None) -> bool:
    value = (name or "").strip().lower()
    return "payload" in value


def _child_order(child: Any) -> tuple[int, str]:
    if isinstance(child, InnerTube):
        kind = 0
    elif isinstance(child, ParachuteRef):
        kind = 1
    elif isinstance(child, TelemetryMass):
        kind = 2
    elif isinstance(child, BallastMass):
        kind = 3
    else:
        kind = 9
    return kind, getattr(child, "id", "")


def _normalize_for_export(assembly: RocketAssembly) -> RocketAssembly:
    # Keep user stage/body ordering exactly as provided, but sanitize geometry/offsets
    # so add/remove edits cannot produce structurally unstable ORK trees.
    normalized = assembly.model_copy(deep=True)

    stage_lengths: dict[str, float] = {}
    for stage in normalized.stages:
        mount = stage.motor_mount
        mount.length_m = min(mount.length_m, stage.length_m)
        max_mount_bottom = max(stage.length_m - mount.length_m, 0.0)
        mount.position_from_bottom_m = _clip(mount.position_from_bottom_m, 0.0, max_mount_bottom)
        stage.bulkhead.position_from_top_m = 0.0
        stage_lengths[stage.id] = stage.length_m

    body_lengths: dict[str, float] = {}
    for tube in normalized.body_tubes:
        body_lengths[tube.id] = tube.length_m
        for child in tube.children:
            if isinstance(child, InnerTube):
                child.length_m = min(child.length_m, tube.length_m)
                max_bottom = max(tube.length_m - child.length_m, 0.0)
                child.position_from_bottom_m = _clip(child.position_from_bottom_m, 0.0, max_bottom)
            elif isinstance(child, ParachuteRef):
                child.position_from_bottom_m = _clip(child.position_from_bottom_m, 0.0, tube.length_m)
            elif isinstance(child, (TelemetryMass, BallastMass)):
                child.position_from_bottom_m = _clip(child.position_from_bottom_m, 0.0, tube.length_m)

        tube.children.sort(
            key=lambda child: (
                getattr(child, "position_from_bottom_m", 0.0),
                *_child_order(child),
            )
        )

    parent_lengths = {**stage_lengths, **body_lengths}
    normalized.fin_sets.sort(key=lambda fin: (fin.parent_tube_id, fin.position_from_bottom_m, fin.id))
    for fin in normalized.fin_sets:
        parent_length = parent_lengths.get(fin.parent_tube_id)
        if parent_length is not None:
            fin.position_from_bottom_m = _clip(fin.position_from_bottom_m, 0.0, parent_length)

    return normalized


def _structure_fingerprint_payload(assembly: RocketAssembly) -> dict[str, Any]:
    return {
        "name": assembly.name,
        "global_diameter_m": assembly.global_diameter_m,
        "nose_cone": {
            "id": assembly.nose_cone.id,
            "type": assembly.nose_cone.type,
            "length_m": assembly.nose_cone.length_m,
            "diameter_m": assembly.nose_cone.diameter_m,
        },
        "stages": [
            {
                "id": stage.id,
                "length_m": stage.length_m,
                "diameter_m": stage.diameter_m,
                "motor_mount": {
                    "id": stage.motor_mount.id,
                    "length_m": stage.motor_mount.length_m,
                    "position_from_bottom_m": stage.motor_mount.position_from_bottom_m,
                },
                "bulkhead": {
                    "id": stage.bulkhead.id,
                    "height_m": stage.bulkhead.height_m,
                    "position_from_top_m": stage.bulkhead.position_from_top_m,
                },
            }
            for stage in assembly.stages
        ],
        "body_tubes": [
            {
                "id": tube.id,
                "length_m": tube.length_m,
                "diameter_m": tube.diameter_m,
                "wall_thickness_m": tube.wall_thickness_m,
                "children": [
                    {
                        "type": child.type,
                        "id": child.id,
                        "position_from_bottom_m": child.position_from_bottom_m,
                        "length_m": getattr(child, "length_m", None),
                        "mass_kg": getattr(child, "mass_kg", None),
                        "diameter_m": getattr(child, "diameter_m", None),
                    }
                    for child in tube.children
                ],
            }
            for tube in assembly.body_tubes
        ],
        "fin_sets": [
            {
                "id": fin.id,
                "parent_tube_id": fin.parent_tube_id,
                "fin_count": fin.fin_count,
                "position_from_bottom_m": fin.position_from_bottom_m,
                "root_chord_m": fin.root_chord_m,
                "tip_chord_m": fin.tip_chord_m,
                "span_m": fin.span_m,
                "sweep_m": fin.sweep_m,
                "thickness_m": fin.thickness_m,
            }
            for fin in assembly.fin_sets
        ],
    }


def _structure_checksum_sha256(assembly: RocketAssembly) -> str:
    payload = _structure_fingerprint_payload(assembly)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _add_motor_mount(inner, rocket, motor_mount: InnerTube, mount_material: str) -> None:
    _safe_set(inner, "setLength", motor_mount.length_m, float)
    _safe_set(inner, "setOuterRadius", motor_mount.outer_diameter_m / 2.0, float)
    if motor_mount.inner_diameter_m:
        _safe_set(inner, "setInnerRadius", motor_mount.inner_diameter_m / 2.0, float)
    _set_position_from_bottom(inner, motor_mount.position_from_bottom_m)
    if motor_mount.is_motor_mount:
        _safe_set(inner, "setMotorMount", True, bool)
        config = None
        if hasattr(rocket, "getSelectedConfiguration"):
            config = rocket.getSelectedConfiguration()
        elif hasattr(rocket, "getDefaultConfiguration"):
            config = rocket.getDefaultConfiguration()
        config_id = config.getId() if config else None
        if config_id is not None:
            try:
                inner.setMotor(config_id, None)
            except Exception:
                try:
                    OR_MotorConfig = jpype.JClass("net.sf.openrocket.motor.MotorConfiguration")
                    mount_cfg = inner.getMotorConfig(config_id)
                    if mount_cfg is None:
                        mount_cfg = OR_MotorConfig(inner, config_id)
                        inner.setMotorConfig(mount_cfg, config_id)
                    _safe_set(inner, "setMotorMount", True, bool)
                    _safe_set(mount_cfg, "setMotor", None)
                except Exception:
                    pass
    _apply_material(inner, mount_material)


def _add_bulkhead(body_tube, stage: Stage, bulkhead: Bulkhead) -> None:
    ring = jpype.JClass("net.sf.openrocket.rocketcomponent.Bulkhead")()
    _safe_set(ring, "setLength", bulkhead.height_m, float)
    _safe_set(ring, "setOuterRadius", stage.diameter_m / 2.0, float)
    position_from_bottom = max(stage.length_m - bulkhead.height_m, 0.0)
    _set_position_from_bottom(ring, position_from_bottom)
    _apply_material(ring, bulkhead.material or "Phenolic")
    body_tube.addChild(ring)


def _add_body_tube_children(body_tube, tube_data: BodyTube) -> None:
    OR_InnerTube = jpype.JClass("net.sf.openrocket.rocketcomponent.InnerTube")
    OR_Parachute = jpype.JClass("net.sf.openrocket.rocketcomponent.Parachute")
    OR_MassComponent = jpype.JClass("net.sf.openrocket.rocketcomponent.MassComponent")

    for child in tube_data.children:
        if isinstance(child, InnerTube):
            inner = OR_InnerTube()
            _safe_set(inner, "setLength", child.length_m, float)
            _safe_set(inner, "setOuterRadius", child.outer_diameter_m / 2.0, float)
            if child.inner_diameter_m:
                _safe_set(inner, "setInnerRadius", child.inner_diameter_m / 2.0, float)
            _set_position_from_bottom(inner, child.position_from_bottom_m)
            _apply_material(inner, "Aluminum 6063-T6" if not child.is_motor_mount else "Phenolic")
            body_tube.addChild(inner)
        elif isinstance(child, ParachuteRef):
            chute = OR_Parachute()
            if child.diameter_m:
                _safe_set(chute, "setDiameter", child.diameter_m, float)
            _set_position_from_bottom(chute, child.position_from_bottom_m)
            _apply_material(chute, "Ripstop nylon", material_type="surface")
            body_tube.addChild(chute)
        elif isinstance(child, TelemetryMass):
            mass_obj = OR_MassComponent()
            _safe_set(mass_obj, "setComponentMass", child.mass_kg, float)
            _safe_set(mass_obj, "setMass", child.mass_kg, float)
            _safe_set(mass_obj, "setOverrideMass", child.mass_kg, float)
            _safe_set(mass_obj, "setMassOverridden", True, bool)
            _safe_set(mass_obj, "setName", child.name)
            _safe_set(mass_obj, "setLength", 0.05, float)
            _safe_set(mass_obj, "setRadius", 0.02, float)
            if _is_payload_named(child.name):
                _set_mass_component_type(mass_obj, "masscomponent")
            else:
                _set_mass_component_type(mass_obj, "flightcomputer")
            _set_position_from_bottom(mass_obj, child.position_from_bottom_m)
            _apply_material(mass_obj, "Aluminum 6063-T6")
            body_tube.addChild(mass_obj)
        elif isinstance(child, BallastMass):
            mass_obj = OR_MassComponent()
            _safe_set(mass_obj, "setComponentMass", child.mass_kg, float)
            _safe_set(mass_obj, "setMass", child.mass_kg, float)
            _safe_set(mass_obj, "setOverrideMass", child.mass_kg, float)
            _safe_set(mass_obj, "setMassOverridden", True, bool)
            _safe_set(mass_obj, "setName", child.name)
            _safe_set(mass_obj, "setLength", 0.06, float)
            _safe_set(mass_obj, "setRadius", 0.025, float)
            _set_mass_component_type(mass_obj, "masscomponent")
            _set_position_from_bottom(mass_obj, child.position_from_bottom_m)
            _apply_material(mass_obj, "Steel")
            body_tube.addChild(mass_obj)
def export_openrocket_ork(assembly: RocketAssembly, output_path: str) -> str:
    ensure_openrocket_initialized()
    source_assembly = assembly
    assembly = _normalize_for_export(assembly)
    checksum = _structure_checksum_sha256(assembly)
    for target in (source_assembly, assembly):
        target.metadata["structure_fingerprint_version"] = "v1"
        target.metadata["structure_checksum_sha256"] = checksum

    # ---------------------------------------------------------
    # 1. Load OpenRocket Java Classes
    # ---------------------------------------------------------
    pkg_comp = "net.sf.openrocket.rocketcomponent"

    OR_Factory = jpype.JClass("net.sf.openrocket.document.OpenRocketDocumentFactory")
    OR_NoseCone = jpype.JClass(f"{pkg_comp}.NoseCone")
    OR_BodyTube = jpype.JClass(f"{pkg_comp}.BodyTube")
    OR_InnerTube = jpype.JClass(f"{pkg_comp}.InnerTube")
    OR_FinSet = jpype.JClass(f"{pkg_comp}.TrapezoidFinSet")
    OR_AxialStage = jpype.JClass(f"{pkg_comp}.AxialStage")

    # ---------------------------------------------------------
    # 2. Create Document & Stage
    # ---------------------------------------------------------
    document = OR_Factory.createNewRocket()
    rocket = document.getRocket()
    stage_shell_material = str(assembly.metadata.get("stage_shell_material") or "Aluminum 6063-T6")
    motor_mount_material = str(assembly.metadata.get("motor_mount_material") or "Aluminum 6063-T6")
    fin_material = str(assembly.metadata.get("source_fin_material") or "Aluminum 6063-T6")
    body_material_lookup: dict[str, str] = {}
    manifest = assembly.metadata.get("component_material_manifest")
    if isinstance(manifest, dict):
        body_entries = manifest.get("body_tube_materials")
        if isinstance(body_entries, list):
            for entry in body_entries:
                if not isinstance(entry, dict):
                    continue
                body_id = entry.get("body_tube_id")
                material = entry.get("material")
                if isinstance(body_id, str) and isinstance(material, str):
                    body_material_lookup[body_id] = material

    # Build true stage hierarchy: Sustainer + optional boosters.
    stage_roots: list[Any] = []
    total_stages = max(1, len(assembly.stages))
    # Stage order in assembly is bottom-up by construction. OpenRocket tree is top-down.
    for idx in range(total_stages):
        if idx == 0:
            stage_root = rocket.getStage(0)
        else:
            stage_root = OR_AxialStage()
            rocket.addChild(stage_root)
        # Name top stage Sustainer, lower stages Booster N.
        if idx == 0:
            _safe_set(stage_root, "setName", "Sustainer")
        else:
            _safe_set(stage_root, "setName", f"Booster {idx}")
        stage_roots.append(stage_root)

    # ---------------------------------------------------------
    # 3. Build Nose Cone
    # ---------------------------------------------------------
    nose = OR_NoseCone()
    _safe_set(nose, "setLength", assembly.nose_cone.length_m, float)
    _safe_set(nose, "setBaseRadius", assembly.nose_cone.diameter_m / 2.0, float)

    # Shape Enum Mapping
    try:
        ShapeEnum = jpype.JClass(f"{pkg_comp}.NoseCone$Shape")
        shape_str = assembly.nose_cone.type.upper()
        if hasattr(ShapeEnum, shape_str):
            nose.setShapeType(getattr(ShapeEnum, shape_str))
    except Exception:
        pass  # Default is usually Ogive

    stage_roots[0].addChild(nose)
    _apply_material(nose, assembly.nose_cone.material or "Fiberglass")

    # ---------------------------------------------------------
    # 4. Build Stages + Body Tubes
    # ---------------------------------------------------------
    component_map: dict[str, Any] = {}

    # Map candidate stage ids to OR stages using reversed order (top-down OpenRocket tree).
    stage_data_order = list(reversed(assembly.stages))
    stage_root_for_id: dict[str, Any] = {}
    for idx, stage_data in enumerate(stage_data_order):
        stage_root_for_id[stage_data.id] = stage_roots[min(idx, len(stage_roots) - 1)]

    for stage_data in assembly.stages:
        stage_tube = OR_BodyTube()
        _safe_set(stage_tube, "setLength", stage_data.length_m, float)
        _safe_set(stage_tube, "setOuterRadius", stage_data.diameter_m / 2.0, float)
        inner_radius = (stage_data.diameter_m / 2.0) - 0.002
        _safe_set(stage_tube, "setInnerRadius", inner_radius, float)
        stage_root = stage_root_for_id.get(stage_data.id, stage_roots[0])
        stage_root.addChild(stage_tube)
        _set_position_from_top(stage_tube, 0.0)
        _apply_material(stage_tube, stage_shell_material)
        component_map[stage_data.id] = stage_tube

        inner = OR_InnerTube()
        _add_motor_mount(inner, rocket, stage_data.motor_mount, motor_mount_material)
        stage_tube.addChild(inner)

        _add_bulkhead(stage_tube, stage_data, stage_data.bulkhead)

    sustainer_cursor_m = 0.0
    for stage_data in stage_data_order:
        sustainer_cursor_m += stage_data.length_m
    for tube_data in assembly.body_tubes:
        body_tube = OR_BodyTube()
        _safe_set(body_tube, "setLength", tube_data.length_m, float)
        _safe_set(body_tube, "setOuterRadius", tube_data.diameter_m / 2.0, float)
        inner_radius = (tube_data.diameter_m / 2.0) - (tube_data.wall_thickness_m or 0.002)
        _safe_set(body_tube, "setInnerRadius", inner_radius, float)
        stage_roots[0].addChild(body_tube)
        _set_position_from_top(body_tube, sustainer_cursor_m)
        _apply_material(body_tube, body_material_lookup.get(tube_data.id, "Aluminum 6063-T6"))
        component_map[tube_data.id] = body_tube
        sustainer_cursor_m += tube_data.length_m

        _add_body_tube_children(body_tube, tube_data)

    # ---------------------------------------------------------
    # 5. Attach Fins (External)
    # ---------------------------------------------------------
    for fin in assembly.fin_sets:
        parent_tube = component_map.get(fin.parent_tube_id)
        if not parent_tube:
            continue

        fin_set = OR_FinSet()
        _safe_set(fin_set, "setFinCount", fin.fin_count, int)
        _safe_set(fin_set, "setRootChord", fin.root_chord_m, float)
        _safe_set(fin_set, "setTipChord", fin.tip_chord_m, float)
        _safe_set(fin_set, "setHeight", fin.span_m, float)
        _safe_set(fin_set, "setSweep", fin.sweep_m, float)
        _safe_set(fin_set, "setThickness", fin.thickness_m or 0.003, float)
        _set_position_from_bottom(fin_set, fin.position_from_bottom_m)
        _apply_material(fin_set, fin_material)
        parent_tube.addChild(fin_set)

    # ---------------------------------------------------------
    # 6. Save File
    # ---------------------------------------------------------
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    return save_openrocket_document(document, str(output))