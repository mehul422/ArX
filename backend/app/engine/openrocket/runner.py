import os
from typing import Any

import jpype
import jpype.imports
import xml.etree.ElementTree as ET

from app.core.config import get_settings
from app.engine.openrocket.eng_parser import EngMotorDefinition, parse_eng_file


def _ensure_jvm(classpath: list[str]) -> None:
    if jpype.isJVMStarted():
        return
    jvm_args: list[str] = []
    jvm_args.append("-Djava.awt.headless=true")
    jvm_args.append("-Dopenrocket.nogui=true")
    logback_config = os.getenv("OPENROCKET_LOGBACK_CONFIG")
    if logback_config and os.path.exists(logback_config):
        jvm_args.append(f"-Dlogback.configurationFile={logback_config}")
    jpype.startJVM(*jvm_args, classpath=classpath)


def _build_classpath(jar_path: str) -> list[str]:
    jar_dir = os.path.dirname(jar_path)
    lib_dir = os.path.join(jar_dir, "lib")
    classpath = [jar_path]
    if os.path.isdir(lib_dir):
        for name in os.listdir(lib_dir):
            if name.lower().endswith(".jar"):
                classpath.append(os.path.join(lib_dir, name))
    return classpath


def _ensure_openrocket_initialized() -> None:
    Application = jpype.JClass("net.sf.openrocket.startup.Application")
    try:
        if Application.getInjector() is not None:
            return
    except Exception:
        # If injector access fails, attempt to reinitialize below.
        pass
    Guice = jpype.JClass("com.google.inject.Guice")
    CoreServicesModule = jpype.JClass("net.sf.openrocket.utils.CoreServicesModule")
    PluginModule = jpype.JClass("net.sf.openrocket.plugin.PluginModule")
    headless = os.getenv("JAVA_TOOL_OPTIONS", "")
    if "java.awt.headless=true" in headless:
        modules = [CoreServicesModule(), PluginModule()]
        try:
            DatabaseModule = jpype.JClass("net.sf.openrocket.database.DatabaseModule")
            modules.insert(1, DatabaseModule())
        except Exception:
            pass
        try:
            ComponentPresetDao = jpype.JClass("net.sf.openrocket.database.ComponentPresetDao")
            ComponentPresetDatabase = jpype.JClass("net.sf.openrocket.database.ComponentPresetDatabase")
            ComponentPresetDatabaseLoader = jpype.JClass(
                "net.sf.openrocket.database.ComponentPresetDatabaseLoader"
            )
            MotorDatabase = jpype.JClass("net.sf.openrocket.database.motor.MotorDatabase")
            ThrustCurveMotorSetDatabase = jpype.JClass(
                "net.sf.openrocket.database.motor.ThrustCurveMotorSetDatabase"
            )

            preset_loader = ComponentPresetDatabaseLoader()
            try:
                preset_db = preset_loader.getDatabase()
            except Exception:
                preset_db = ComponentPresetDatabase()
            motor_db = ThrustCurveMotorSetDatabase()

            class _PresetModule:
                def configure(self, binder):
                    binder.bind(ComponentPresetDao).toInstance(preset_db)
                    binder.bind(ComponentPresetDatabase).toInstance(preset_db)
                    binder.bind(MotorDatabase).toInstance(motor_db)

            preset_module = jpype.JProxy("com.google.inject.Module", inst=_PresetModule())
            modules.append(preset_module)
        except Exception:
            pass
        injector = Guice.createInjector(*modules)
    else:
        Modules = jpype.JClass("com.google.inject.util.Modules")
        GuiModule = jpype.JClass("net.sf.openrocket.startup.GuiModule")
        gui_module = GuiModule()
        overridden_builder = Modules.override(CoreServicesModule())
        overridden = getattr(overridden_builder, "with_")(gui_module)
        injector = Guice.createInjector(overridden, PluginModule())
    Application.setInjector(injector)
    try:
        if "java.awt.headless=true" not in headless:
            gui_module.startLoader()
    except Exception:
        # Loader may attempt UI; ignore for headless mode.
        pass


def _ensure_openrocket_core_initialized() -> None:
    Application = jpype.JClass("info.openrocket.core.startup.Application")
    try:
        if Application.getInjector() is not None:
            return
    except Exception:
        pass

    Guice = jpype.JClass("com.google.inject.Guice")
    CoreServicesModule = jpype.JClass("info.openrocket.swing.utils.CoreServicesModule")
    PluginModule = jpype.JClass("info.openrocket.core.plugin.PluginModule")
    modules = [CoreServicesModule(), PluginModule()]

    try:
        ComponentPresetDao = jpype.JClass("info.openrocket.core.database.ComponentPresetDao")
        ComponentPresetDatabase = jpype.JClass("info.openrocket.core.database.ComponentPresetDatabase")
        ComponentPresetDatabaseLoader = jpype.JClass(
            "info.openrocket.core.database.ComponentPresetDatabaseLoader"
        )
        MotorDatabase = jpype.JClass("info.openrocket.core.database.motor.MotorDatabase")
        ThrustCurveMotorSetDatabase = jpype.JClass(
            "info.openrocket.core.database.motor.ThrustCurveMotorSetDatabase"
        )

        preset_loader = ComponentPresetDatabaseLoader()
        try:
            preset_db = preset_loader.getDatabase()
        except Exception:
            preset_db = ComponentPresetDatabase()

        motor_db = ThrustCurveMotorSetDatabase()

        class _PresetModule:
            def configure(self, binder):
                binder.bind(ComponentPresetDao).toInstance(preset_db)
                binder.bind(ComponentPresetDatabase).toInstance(preset_db)
                binder.bind(MotorDatabase).toInstance(motor_db)

        preset_module = jpype.JProxy("com.google.inject.Module", inst=_PresetModule())
        modules.append(preset_module)
    except Exception:
        pass

    injector = Guice.createInjector(*modules)
    Application.setInjector(injector)


def _get_motor_config(component, config_id):
    try:
        return component.getMotorConfig(config_id)
    except Exception:
        pass
    try:
        return component.getMotorConfiguration().get(config_id)
    except Exception:
        return None


def _get_default_motor_config(component):
    try:
        return component.getDefaultMotorConfig()
    except Exception:
        pass
    try:
        return component.getMotorConfiguration().getDefault()
    except Exception:
        return None


def _set_motor_config(component, config_id, motor_config) -> bool:
    try:
        component.setMotorConfig(config_id, motor_config)
        return True
    except Exception:
        pass
    try:
        component.getMotorConfiguration().set(config_id, motor_config)
        return True
    except Exception:
        return False


def _apply_motor_to_mounts(rocket, config_id, motor, motor_length_m: float | None = None) -> None:
    MotorMount = jpype.JClass("net.sf.openrocket.rocketcomponent.MotorMount")
    Motor = jpype.JClass("net.sf.openrocket.motor.Motor")
    motor_length = motor_length_m
    if motor_length is None:
        try:
            motor_length = float(motor.getLength()) if isinstance(motor, Motor) else None
        except Exception:
            motor_length = None
    stack = [rocket]
    while stack:
        component = stack.pop()
        try:
            if isinstance(component, MotorMount):
                motor_config = _get_motor_config(component, config_id)
                if motor_config is None:
                    motor_config = _get_default_motor_config(component)
                if motor_config is not None:
                    motor_config.setMotor(motor)
                    _set_motor_config(component, config_id, motor_config)
                if motor_length is not None:
                    try:
                        mount_length = float(component.getLength())
                    except Exception:
                        mount_length = None
                    if mount_length is not None:
                        try:
                            overhang = max(0.0, float(motor_length) - float(mount_length))
                            component.setMotorOverhang(overhang)
                        except Exception:
                            pass
        except Exception:
            # Skip components that do not support motor configuration
            pass
        for child in component.getChildren():
            stack.append(child)


def _motor_mass_kg(motor) -> float | None:
    getters = ("getTotalMass", "getMass", "getLaunchMass", "getPropellantMass")
    for name in getters:
        try:
            value = getattr(motor, name)()
            if value is not None:
                return float(value)
        except Exception:
            continue
    return None


def _motor_mount_stage_numbers(rocket) -> list[int]:
    MotorMount = jpype.JClass("net.sf.openrocket.rocketcomponent.MotorMount")
    stages: list[int] = []
    for component in _iter_components(rocket):
        try:
            if isinstance(component, MotorMount):
                stages.append(int(component.getStageNumber()))
        except Exception:
            continue
    return stages


def _motor_mounts_by_stage(rocket) -> list[tuple[Any, int]]:
    MotorMount = jpype.JClass("net.sf.openrocket.rocketcomponent.MotorMount")
    mounts: list[tuple[Any, int]] = []
    for component in _iter_components(rocket):
        try:
            if isinstance(component, MotorMount):
                mounts.append((component, int(component.getStageNumber())))
        except Exception:
            continue
    return mounts


def _motor_mounts_for_config(rocket, config_id: str | None) -> list[tuple[Any, Any | None]]:
    MotorMount = jpype.JClass("net.sf.openrocket.rocketcomponent.MotorMount")
    mounts: list[tuple[Any, Any | None]] = []
    if not config_id:
        return mounts
    for component in _iter_components(rocket):
        try:
            if not isinstance(component, MotorMount):
                continue
            motor_config = _get_motor_config(component, config_id)
            if motor_config is None:
                continue
            mounts.append((component, motor_config.getMotor()))
        except Exception:
            continue
    return mounts


def _update_tube_diameter(component, diameter_m: float) -> None:
    radius = diameter_m / 2.0
    thickness = None
    try:
        thickness = float(component.getThickness())
    except Exception:
        thickness = None
    if thickness is None:
        try:
            inner_radius = float(component.getInnerRadius())
        except Exception:
            inner_radius = 0.0
        try:
            outer_radius = float(component.getOuterRadius())
        except Exception:
            outer_radius = inner_radius
        thickness = max(0.0, outer_radius - inner_radius)
    component.setInnerRadius(radius)
    component.setOuterRadius(max(radius + thickness, radius))


def _adjust_motor_geometry(mount, motor_length_m: float, motor_diameter_m: float) -> dict[str, Any]:
    BodyTube = jpype.JClass("net.sf.openrocket.rocketcomponent.BodyTube")
    InnerTube = jpype.JClass("net.sf.openrocket.rocketcomponent.InnerTube")
    info: dict[str, Any] = {}
    original_inner_length = None
    try:
        if isinstance(mount, InnerTube):
            info["mount_id"] = str(mount.getID())
            info["mount_name"] = str(mount.getName())
            info["mount_length_before_m"] = float(mount.getLength())
            original_inner_length = float(mount.getLength())
            mount.setLength(float(motor_length_m))
            _update_tube_diameter(mount, motor_diameter_m)
            info["mount_length_after_m"] = float(mount.getLength())
    except Exception:
        pass
    try:
        parent = mount.getParent()
        if isinstance(parent, BodyTube):
            info["parent_id"] = str(parent.getID())
            info["parent_name"] = str(parent.getName())
            info["parent_length_before_m"] = float(parent.getLength())
            current_length = float(parent.getLength())
            if original_inner_length is not None:
                delta = motor_length_m - original_inner_length
                if delta != 0:
                    parent.setLength(float(max(current_length + delta, 0.0)))
            elif motor_length_m > current_length:
                parent.setLength(float(motor_length_m))
            # Keep parent body tube diameter unchanged to avoid
            # unintentionally shrinking the airframe.
            info["parent_length_after_m"] = float(parent.getLength())
    except Exception:
        pass
    return info


def _preview_motor_geometry(mount, motor_length_m: float, motor_diameter_m: float) -> dict[str, Any]:
    BodyTube = jpype.JClass("net.sf.openrocket.rocketcomponent.BodyTube")
    InnerTube = jpype.JClass("net.sf.openrocket.rocketcomponent.InnerTube")
    info: dict[str, Any] = {}
    original_inner_length = None
    try:
        if isinstance(mount, InnerTube):
            info["mount_id"] = str(mount.getID())
            info["mount_name"] = str(mount.getName())
            info["mount_length_before_m"] = float(mount.getLength())
            original_inner_length = float(mount.getLength())
            info["mount_length_after_m"] = float(motor_length_m)
    except Exception:
        pass
    try:
        parent = mount.getParent()
        if isinstance(parent, BodyTube):
            info["parent_id"] = str(parent.getID())
            info["parent_name"] = str(parent.getName())
            info["parent_length_before_m"] = float(parent.getLength())
            current_length = float(parent.getLength())
            if original_inner_length is not None:
                delta = motor_length_m - original_inner_length
                if delta != 0:
                    current_length = max(current_length + delta, 0.0)
            elif motor_length_m > current_length:
                current_length = float(motor_length_m)
            info["parent_length_after_m"] = float(current_length)
    except Exception:
        pass
    return info


def _add_motor_mass_component(mount, motor_mass_kg: float) -> bool:
    MassComponent = jpype.JClass("net.sf.openrocket.rocketcomponent.MassComponent")
    try:
        mass_component = MassComponent()
        mass_component.setComponentMass(float(motor_mass_kg))
    except Exception:
        return False
    try:
        Position = jpype.JClass("net.sf.openrocket.rocketcomponent.RocketComponent$Position")
        mass_component.setRelativePosition(Position.BOTTOM)
    except Exception:
        pass
    try:
        mount.addChild(mass_component)
        return True
    except Exception:
        return False
    except Exception:
        return False


def _make_warning_set():
    candidates = (
        "net.sf.openrocket.aerodynamics.WarningSet",
        "net.sf.openrocket.logging.WarningSet",
    )
    for class_path in candidates:
        try:
            return jpype.JClass(class_path)()
        except Exception:
            continue
    return None


def _compute_cp(cp_calc, configuration, flight_conditions):
    warning_set = _make_warning_set()
    if warning_set is not None:
        return cp_calc.getCP(configuration, flight_conditions, warning_set)
    try:
        return cp_calc.getCP(configuration, flight_conditions)
    except Exception as exc:
        raise RuntimeError("OpenRocket WarningSet class not found") from exc


def _is_float_token(value: str) -> bool:
    try:
        float(value)
        return True
    except Exception:
        return False


def _normalize_eng_header_line(line: str) -> str:
    parts = line.split()
    if len(parts) == 7:
        return line
    first_num = None
    for idx, token in enumerate(parts):
        if _is_float_token(token):
            first_num = idx
            break
    if first_num is None or first_num + 4 >= len(parts):
        return line
    name_tokens = parts[:first_num]
    name = "_".join(name_tokens) if name_tokens else parts[0]
    diameter = parts[first_num]
    length = parts[first_num + 1]
    delays = parts[first_num + 2]
    prop_mass = parts[first_num + 3]
    total_mass = parts[first_num + 4]
    manufacturer = parts[first_num + 5] if first_num + 5 < len(parts) else "unknown"
    return " ".join([name, diameter, length, delays, prop_mass, total_mass, manufacturer])


def _normalized_motor_path_for_openrocket(motor_path: str) -> tuple[str, str | None]:
    try:
        with open(motor_path, "r", encoding="utf-8", errors="ignore") as handle:
            lines = handle.readlines()
    except Exception:
        return motor_path, None
    header_index = None
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith(";") or stripped.startswith("#"):
            continue
        header_index = idx
        break
    if header_index is None:
        return motor_path, None
    original = lines[header_index].strip()
    normalized = _normalize_eng_header_line(original)
    if normalized == original:
        return motor_path, None
    import tempfile

    temp = tempfile.NamedTemporaryFile("w", delete=False, suffix=".eng")
    try:
        lines[header_index] = normalized + "\n"
        temp.writelines(lines)
        temp_path = temp.name
    finally:
        temp.close()
    return temp_path, temp_path


def _compute_stage_metrics(
    configuration,
    mass_calc,
    cp_calc,
    flight_conditions,
    stage_diameters: dict[int, float] | None = None,
) -> list[dict[str, Any]]:
    stage_count = int(configuration.getStageCount())
    metrics: list[dict[str, Any]] = []
    for stage_number in range(stage_count):
        configuration.setOnlyStage(stage_number)
        cg = mass_calc(configuration)
        cp = _compute_cp(cp_calc, configuration, flight_conditions)
        stability_margin = None
        stage_diameter_m = None
        if stage_diameters is not None:
            stage_diameter_m = stage_diameters.get(stage_number)
        if stage_diameter_m is not None and stage_diameter_m > 0:
            stability_margin = float((cp.x - cg.x) / stage_diameter_m)
        metrics.append(
            {
                "stage": stage_number,
                "mass_lb": _to_pounds(float(cg.weight)),
                "cg_in": _to_inches(float(cg.x)),
                "cp_in": _to_inches(float(cp.x)),
                "stability_margin": stability_margin,
            }
        )
    configuration.setAllStages()
    return metrics


def _stage_bodytube_diameters(rocket) -> dict[int, float]:
    BodyTube = jpype.JClass("net.sf.openrocket.rocketcomponent.BodyTube")
    diameters: dict[int, float] = {}
    for component in _iter_components(rocket):
        try:
            if not isinstance(component, BodyTube):
                continue
            stage_number = int(component.getStageNumber())
            outer_radius = float(component.getOuterRadius())
            diameter = outer_radius * 2.0
            if stage_number not in diameters or diameter > diameters[stage_number]:
                diameters[stage_number] = diameter
        except Exception:
            continue
    return diameters


def _compute_stage_masses(mass_calc, config) -> dict[int, float]:
    stage_masses: dict[int, float] = {}
    stage_count = int(config.getStageCount())
    for stage_number in range(stage_count):
        config.setOnlyStage(stage_number)
        cg = mass_calc(config)
        stage_masses[stage_number] = float(cg.weight)
    config.setAllStages()
    return stage_masses


def _launch_mass_calc(configuration):
    try:
        MassCalculator = jpype.JClass("net.sf.openrocket.masscalc.MassCalculator")
        MassCalculationType = jpype.JClass("net.sf.openrocket.masscalc.MassCalculation$Type")
        rigid_body = MassCalculator.calculate(MassCalculationType.LAUNCH, configuration, 0.0)
        center = rigid_body.getCM()
        mass = float(rigid_body.getMass())
        return type(
            "Cg",
            (),
            {"x": float(center.x), "y": float(center.y), "z": float(center.z), "weight": mass},
        )
    except Exception:
        BasicMassCalculator = jpype.JClass("net.sf.openrocket.masscalc.BasicMassCalculator")
        MassCalcType = jpype.JClass("net.sf.openrocket.masscalc.MassCalculator$MassCalcType")
        mass_calc = BasicMassCalculator()
        return mass_calc.getCG(configuration, MassCalcType.LAUNCH_MASS)


def _to_inches(value_m: float) -> float:
    return value_m * 39.3700787402


def _to_pounds(value_kg: float) -> float:
    return value_kg * 2.20462262185


def _material_type_from_name(type_name: str):
    MaterialType = jpype.JClass("net.sf.openrocket.material.Material$Type")
    for value in MaterialType.values():
        if str(value.name()).upper() == type_name.upper():
            return value
    raise ValueError(f"Unsupported material type: {type_name}")


def _material_from_spec(spec: dict[str, Any]):
    Material = jpype.JClass("net.sf.openrocket.material.Material")
    material_type = _material_type_from_name(spec.get("type", "BULK"))
    name = spec.get("name", "Custom")
    density = float(spec.get("density_kg_m3", 0.0))
    return Material.newMaterial(material_type, name, density, True)


def _material_catalog() -> list[dict[str, Any]]:
    return [
        {"name": "Fiberglass", "density_kg_m3": 1850.0, "type": "BULK"},
        {"name": "Carbon Fiber", "density_kg_m3": 1600.0, "type": "BULK"},
        {"name": "Aluminum 6061-T6", "density_kg_m3": 2700.0, "type": "BULK"},
        {"name": "Steel 4130", "density_kg_m3": 7850.0, "type": "BULK"},
        {"name": "Kraft Phenolic", "density_kg_m3": 1200.0, "type": "BULK"},
        {"name": "Phenolic", "density_kg_m3": 1350.0, "type": "BULK"},
        {"name": "Graphite", "density_kg_m3": 1800.0, "type": "BULK"},
        {"name": "Titanium", "density_kg_m3": 4430.0, "type": "BULK"},
        {"name": "Inconel 718", "density_kg_m3": 8190.0, "type": "BULK"},
    ]


def _material_by_name(name: str) -> dict[str, Any] | None:
    for material in _material_catalog():
        if material["name"].lower() == name.lower():
            return material
    return None


def _recommend_component_material(component, pressure_pa: float | None) -> dict[str, Any] | None:
    name = str(component.getName()).lower()
    class_name = str(component.getClass().getName()).lower()

    if "liner" in name:
        return _material_by_name("Kraft Phenolic")
    if "thrust chamber" in name or "chamber" in name or "case" in name:
        return _material_by_name("Aluminum 6061-T6")
    if "nozzle" in name:
        return _material_by_name("Graphite")
    if "fin" in name:
        return _material_by_name("Carbon Fiber")
    if any(token in name for token in ("avionics", "telemetry", "electronics", "payload")):
        return _material_by_name("Fiberglass")
    if "motor mount" in name or "motor tube" in name:
        return _material_by_name("Aluminum 6061-T6")
    if "coupler" in name or "bulkhead" in name:
        return _material_by_name("Fiberglass")
    if "body tube" in name or "airframe" in name or "bodytube" in class_name:
        return _material_by_name("Fiberglass")

    if pressure_pa is not None:
        return _recommend_material(pressure_pa)
    return None


def _auto_material_overrides(rocket, pressure_pa: float | None) -> dict[str, dict[str, Any]]:
    ExternalComponent = jpype.JClass("net.sf.openrocket.rocketcomponent.ExternalComponent")
    overrides: dict[str, dict[str, Any]] = {}
    for component in _iter_components(rocket):
        if not isinstance(component, ExternalComponent):
            continue
        recommendation = _recommend_component_material(component, pressure_pa)
        if recommendation:
            overrides[str(component.getID())] = recommendation
    return overrides


def _recommend_material(pressure_pa: float | None) -> dict[str, Any] | None:
    if pressure_pa is None:
        return None
    # Simple heuristic; tune once we align with OpenRocket expectations.
    if pressure_pa <= 2_000_000:
        return {"name": "Fiberglass", "density_kg_m3": 1850.0, "type": "BULK"}
    if pressure_pa <= 5_000_000:
        return {"name": "Aluminum 6061", "density_kg_m3": 2700.0, "type": "BULK"}
    if pressure_pa <= 10_000_000:
        return {"name": "Steel 4130", "density_kg_m3": 7850.0, "type": "BULK"}
    return None


def _iter_components(rocket):
    stack = [rocket]
    while stack:
        component = stack.pop()
        yield component
        for child in component.getChildren():
            stack.append(child)


def _collect_components(rocket, recommendations: dict[str, dict[str, Any]] | None = None):
    ExternalComponent = jpype.JClass("net.sf.openrocket.rocketcomponent.ExternalComponent")
    components = []
    for component in _iter_components(rocket):
        info = {
            "id": str(component.getID()),
            "name": str(component.getName()),
            "class": str(component.getClass().getName()),
        }
        try:
            info["stage_number"] = int(component.getStageNumber())
        except Exception:
            info["stage_number"] = None
        if isinstance(component, ExternalComponent):
            material = component.getMaterial()
            if material:
                info["material"] = {
                    "name": str(material.getName()),
                    "density_kg_m3": float(material.getDensity()),
                    "type": str(material.getType().name()),
                }
        if recommendations and info["id"] in recommendations:
            info["recommended_material"] = recommendations[info["id"]]
        components.append(info)
    return components


def _apply_materials(rocket, material_default, material_overrides):
    ExternalComponent = jpype.JClass("net.sf.openrocket.rocketcomponent.ExternalComponent")
    overrides = material_overrides or {}
    default_material = _material_from_spec(material_default) if material_default else None
    for component in _iter_components(rocket):
        if not isinstance(component, ExternalComponent):
            continue
        override = overrides.get(str(component.getID()))
        if override:
            component.setMaterial(_material_from_spec(override))
        elif default_material is not None:
            component.setMaterial(default_material)


def _select_configuration(document, flight_config_id: str | None, use_all_stages: bool):
    rocket = document.getRocket()
    try:
        configuration = document.getDefaultConfiguration()
    except Exception:
        try:
            configuration = document.getSelectedConfiguration()
        except Exception:
            configuration = rocket.getSelectedConfiguration()

    if flight_config_id:
        try:
            configuration.setFlightConfigurationID(flight_config_id)
        except Exception:
            try:
                FlightConfigurationId = jpype.JClass(
                    "net.sf.openrocket.rocketcomponent.FlightConfigurationId"
                )
                config_id = FlightConfigurationId(flight_config_id)
                config_candidate = rocket.getFlightConfiguration(config_id)
                if config_candidate is not None:
                    configuration = config_candidate
                    try:
                        rocket.setSelectedConfiguration(config_candidate)
                    except Exception:
                        pass
            except Exception:
                pass

    if use_all_stages:
        try:
            configuration.setAllStages()
        except Exception:
            pass
    else:
        try:
            active_ids = list(rocket.getFlightConfigurationIDs())
            if active_ids:
                configuration.setFlightConfigurationID(active_ids[0])
        except Exception:
            pass
    return configuration


def _default_motor_config_id(rocket_path: str) -> str | None:
    try:
        tree = ET.parse(rocket_path)
    except Exception:
        return None
    root = tree.getroot()
    for motor_config in root.findall(".//motorconfiguration"):
        if motor_config.attrib.get("default") == "true":
            return motor_config.attrib.get("configid")
    return None


def _motor_mount_component_ids(rocket_path: str) -> set[str]:
    try:
        tree = ET.parse(rocket_path)
    except Exception:
        return set()
    root = tree.getroot()
    mount_ids: set[str] = set()
    for inner_tube in root.findall(".//innertube"):
        has_mount = inner_tube.find("motormount") is not None
        if not has_mount:
            continue
        id_node = inner_tube.find("id")
        if id_node is not None and id_node.text:
            mount_ids.add(id_node.text.strip())
    return mount_ids


def _select_core_configuration(document, flight_config_id: str | None, use_all_stages: bool):
    rocket = document.getRocket()
    try:
        configuration = document.getDefaultConfiguration()
    except Exception:
        try:
            configuration = document.getSelectedConfiguration()
        except Exception:
            configuration = rocket.getSelectedConfiguration()

    if flight_config_id:
        try:
            configuration.setFlightConfigurationID(flight_config_id)
        except Exception:
            try:
                FlightConfigurationId = jpype.JClass(
                    "info.openrocket.core.rocketcomponent.FlightConfigurationId"
                )
                config_id = FlightConfigurationId(flight_config_id)
                config_candidate = rocket.getFlightConfiguration(config_id)
                if config_candidate is not None:
                    configuration = config_candidate
                    try:
                        rocket.setSelectedConfiguration(config_candidate)
                    except Exception:
                        pass
            except Exception:
                pass

    if use_all_stages:
        try:
            configuration.setAllStages()
        except Exception:
            pass
    else:
        try:
            active_ids = list(rocket.getFlightConfigurationIDs())
            if active_ids:
                configuration.setFlightConfigurationID(active_ids[0])
        except Exception:
            pass
    return configuration


def _xml_position_value(element) -> tuple[float | None, str | None]:
    pos_node = element.find("position")
    if pos_node is None:
        pos_node = element.find("axialoffset")
    if pos_node is None or pos_node.text is None:
        return None, None
    try:
        value = float(pos_node.text)
    except Exception:
        return None, None
    pos_type = pos_node.get("type") or pos_node.get("method")
    return value, pos_type


def _absolute_z(parent_start_z: float, parent_length: float, element) -> float:
    value, pos_type = _xml_position_value(element)
    if value is None:
        return parent_start_z
    normalized = (pos_type or "top").lower()
    if normalized == "absolute":
        return value
    if normalized == "bottom":
        return parent_start_z + parent_length - value
    return parent_start_z + value


def _compute_custom_cg_from_xml(
    rocket_path: str,
    sustainer_motor_mass_kg: float | None,
    booster_motor_mass_kg: float | None,
    target_mount_ids: set[str] | None,
    motor_cg_offset_m: float = 0.34,
) -> tuple[float | None, float]:
    try:
        tree = ET.parse(rocket_path)
    except Exception:
        return None, 0.0
    root = tree.getroot()
    rocket = root if root.tag == "rocket" else root.find("rocket")
    if rocket is None:
        return None, 0.0
    rocket_subs = rocket.find("subcomponents")
    if rocket_subs is None:
        return None, 0.0

    total_mass = 0.0
    total_moment = 0.0

    def process_tube_contents(
        tube_element, tube_start_z: float, tube_length: float, stage_name: str | None
    ) -> None:
        nonlocal total_mass, total_moment
        subs = tube_element.find("subcomponents")
        if subs is None:
            return
        for child in subs:
            child_z = _absolute_z(tube_start_z, tube_length, child)
            mass_node = child.find("mass")
            override_node = child.find("overridemass")
            if mass_node is not None and mass_node.text:
                try:
                    mass = float(mass_node.text)
                except Exception:
                    mass = None
            elif override_node is not None and override_node.text:
                try:
                    mass = float(override_node.text)
                except Exception:
                    mass = None
            else:
                mass = None
            if mass is not None:
                total_mass += mass
                total_moment += mass * child_z

            if child.tag == "innertube" and child.find("motormount") is not None:
                include_mount = True
                if target_mount_ids is not None:
                    id_node = child.find("id")
                    child_id = id_node.text.strip() if id_node is not None and id_node.text else None
                    include_mount = child_id in target_mount_ids if child_id else False
                if include_mount:
                    motor_mass = None
                    stage_token = (stage_name or "").lower()
                    if "sustainer" in stage_token:
                        motor_mass = sustainer_motor_mass_kg
                    elif "booster" in stage_token:
                        motor_mass = booster_motor_mass_kg
                    if motor_mass is None or motor_mass <= 0:
                        continue
                    motor_cg_z = tube_start_z + tube_length - motor_cg_offset_m
                    total_mass += motor_mass
                    total_moment += motor_mass * motor_cg_z

    running_z = 0.0
    for stage in rocket_subs:
        if stage.tag != "stage":
            continue
        stage_name = None
        stage_name_node = stage.find("name")
        if stage_name_node is not None and stage_name_node.text:
            stage_name = stage_name_node.text.strip()
        stage_subs = stage.find("subcomponents")
        if stage_subs is None:
            continue
        for comp in stage_subs:
            if comp.tag not in ("nosecone", "bodytube", "transition"):
                continue
            length = 0.0
            length_node = comp.find("length")
            if length_node is not None and length_node.text:
                try:
                    length = float(length_node.text)
                except Exception:
                    length = 0.0
            process_tube_contents(comp, running_z, length, stage_name)
            running_z += length

    if total_mass <= 0:
        return None, 0.0
    return total_moment / total_mass, total_mass


def run_openrocket_simulation(params: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    jar_path = params.get("openrocket_jar") or settings.openrocket_jar
    if not jar_path:
        raise RuntimeError("OPENROCKET_JAR not configured")
    if not os.path.exists(jar_path):
        raise FileNotFoundError(f"OpenRocket jar not found: {jar_path}")

    classpath = _build_classpath(jar_path)
    _ensure_jvm(classpath)
    _ensure_openrocket_initialized()

    rocket_path = params.get("rocket_path")
    motor_path = params.get("motor_path")
    if not rocket_path or not os.path.exists(rocket_path):
        raise FileNotFoundError("rocket_path not found")
    if not motor_path:
        if not params.get("allow_missing_motor"):
            raise FileNotFoundError("motor_path not found")
    elif not os.path.exists(motor_path):
        raise FileNotFoundError("motor_path not found")

    GeneralRocketLoader = jpype.JClass("net.sf.openrocket.file.GeneralRocketLoader")
    GeneralMotorLoader = jpype.JClass("net.sf.openrocket.file.motor.GeneralMotorLoader")
    BarrowmanCalculator = jpype.JClass("net.sf.openrocket.aerodynamics.BarrowmanCalculator")
    FlightConditions = jpype.JClass("net.sf.openrocket.aerodynamics.FlightConditions")
    FileInputStream = jpype.JClass("java.io.FileInputStream")
    File = jpype.JClass("java.io.File")

    document = GeneralRocketLoader(File(rocket_path)).load()
    rocket = document.getRocket()
    requested_config_id = params.get("flight_config_id")
    default_config_id = _default_motor_config_id(rocket_path)
    configuration = _select_configuration(
        document,
        requested_config_id or default_config_id,
        bool(params.get("use_all_stages", True)),
    )
    config_id = configuration.getFlightConfigurationID()
    motor_mount_ids = _motor_mount_component_ids(rocket_path)

    motor_mass_kg = None
    motor_length_m = params.get("motor_length_m")

    pressure_pa = params.get("pressure_pa")
    if pressure_pa is None:
        try:
            pressure_pa = float(params.get("chamber_pressure"))
        except Exception:
            pressure_pa = None

    material_mode = params.get("material_mode", "auto")
    material_default = params.get("material_default")
    material_overrides = params.get("material_overrides")
    recommended_material = _recommend_material(pressure_pa)

    auto_overrides = None
    if material_mode == "auto":
        auto_overrides = _auto_material_overrides(rocket, pressure_pa)
        if auto_overrides:
            merged_overrides = dict(auto_overrides)
            if material_overrides:
                merged_overrides.update(material_overrides)
            material_overrides = merged_overrides
        if material_default is None and not material_overrides:
            material_default = recommended_material

    if material_mode == "auto" or material_mode == "custom":
        if material_default or material_overrides:
            _apply_materials(rocket, material_default, material_overrides)

    mass_calc = _launch_mass_calc
    base_cg = mass_calc(configuration)
    target_mounts: list[Any] = []
    desired_motor_mass_kg: float | None = None
    expected_motor_mass_kg: float | None = None

    if motor_path:
        motor_loader = GeneralMotorLoader()
        normalized_path, temp_path = _normalized_motor_path_for_openrocket(motor_path)
        stream = FileInputStream(normalized_path)
        try:
            motors = motor_loader.load(stream, os.path.basename(normalized_path))
        finally:
            stream.close()
            if temp_path:
                try:
                    os.remove(temp_path)
                except Exception:
                    pass

        if motors.size() == 0:
            raise RuntimeError("No motors found in .eng file")
        motor = motors.get(0)
        motor_mass_kg = _motor_mass_kg(motor)

        mounts_with_config = _motor_mounts_for_config(rocket, config_id)
        if motor_mount_ids:
            mounts_with_config = [
                (mount, configured_motor)
                for mount, configured_motor in mounts_with_config
                if str(mount.getID()) in motor_mount_ids
            ]
        target_mounts = [mount for mount, _ in mounts_with_config]
        if not target_mounts:
            mounts = _motor_mounts_by_stage(rocket)
            mounts.sort(key=lambda item: item[1])
            if motor_mount_ids:
                target_mounts = [
                    mount for mount, _ in mounts if str(mount.getID()) in motor_mount_ids
                ]
            if not target_mounts:
                target_stage = mounts[0][1] if mounts else 0
                target_mounts = [mount for mount, stage in mounts if stage == target_stage]
                if motor_mount_ids:
                    target_mounts = [
                        mount for mount in target_mounts if str(mount.getID()) in motor_mount_ids
                    ]
            if not target_mounts:
                target_mounts = [mount for mount, _ in mounts]
                if motor_mount_ids:
                    target_mounts = [
                        mount for mount in target_mounts if str(mount.getID()) in motor_mount_ids
                    ]

        if motor_length_m is None:
            for _, configured_motor in mounts_with_config:
                try:
                    if configured_motor is not None:
                        motor_length_m = float(configured_motor.getLength())
                        break
                except Exception:
                    continue
        if motor_length_m is None:
            try:
                motor_length_m = float(motor.getLength())
            except Exception:
                motor_length_m = None

        _apply_motor_to_mounts(rocket, config_id, motor, motor_length_m)

        manual_motor_mass_kg = params.get("motor_mass_kg")
        if manual_motor_mass_kg is not None:
            desired_motor_mass_kg = float(manual_motor_mass_kg)
        elif motor_mass_kg is not None:
            desired_motor_mass_kg = float(motor_mass_kg)

        if desired_motor_mass_kg is not None and desired_motor_mass_kg > 0:
            expected_motor_mass_kg = desired_motor_mass_kg * max(len(target_mounts), 1)
            extra_motor_mass_kg = desired_motor_mass_kg
            if motor_mass_kg is not None:
                extra_motor_mass_kg = max(0.0, desired_motor_mass_kg - float(motor_mass_kg))
            if extra_motor_mass_kg > 0 and target_mounts:
                for mount in target_mounts:
                    _add_motor_mass_component(mount, extra_motor_mass_kg)


        try:
            rocket.setSelectedConfiguration(configuration)
        except Exception:
            pass
        configuration = _select_configuration(
            document,
            requested_config_id or default_config_id,
            bool(params.get("use_all_stages", True)),
        )

    target_mount_ids = {str(mount.getID()) for mount in target_mounts} if target_mounts else None
    motor_cg_offset_m = float(params.get("motor_cg_offset_m", 0.34))
    sustainer_motor_mass_kg = params.get("sustainer_motor_mass_kg")
    booster_motor_mass_kg = params.get("booster_motor_mass_kg")
    custom_cg_x_m, _ = _compute_custom_cg_from_xml(
        rocket_path,
        float(sustainer_motor_mass_kg) if sustainer_motor_mass_kg is not None else None,
        float(booster_motor_mass_kg) if booster_motor_mass_kg is not None else None,
        target_mount_ids,
        motor_cg_offset_m=motor_cg_offset_m,
    )

    cg = mass_calc(configuration)
    custom_cg_x_m = custom_cg_x_m if custom_cg_x_m is not None else float(cg.x)

    if expected_motor_mass_kg is not None and expected_motor_mass_kg > 0 and target_mounts:
        observed_motor_mass_kg = max(0.0, float(cg.weight) - float(base_cg.weight))
        if observed_motor_mass_kg < expected_motor_mass_kg * 0.9:
            missing_motor_mass_kg = max(0.0, expected_motor_mass_kg - observed_motor_mass_kg)
            if missing_motor_mass_kg > 0:
                per_mount_missing = missing_motor_mass_kg / len(target_mounts)
                before_weight = float(cg.weight)
                for mount in target_mounts:
                    _add_motor_mass_component(mount, per_mount_missing)
                try:
                    rocket.setSelectedConfiguration(configuration)
                except Exception:
                    pass
                configuration = _select_configuration(
                    document,
                    requested_config_id or default_config_id,
                    bool(params.get("use_all_stages", True)),
                )
                cg = mass_calc(configuration)
                if abs(float(cg.weight) - before_weight) < 1e-6:
                    for mount in target_mounts:
                        try:
                            parent = mount.getParent()
                        except Exception:
                            parent = None
                        if parent is not None:
                            _add_motor_mass_component(parent, per_mount_missing)
                    try:
                        rocket.setSelectedConfiguration(configuration)
                    except Exception:
                        pass
                    configuration = _select_configuration(
                        document,
                        requested_config_id or default_config_id,
                        bool(params.get("use_all_stages", True)),
                    )
                    cg = mass_calc(configuration)

    flight_conditions = FlightConditions(configuration)
    flight_conditions.setAOA(0.0)
    try:
        Application = jpype.JClass("net.sf.openrocket.startup.Application")
        preferences = Application.getPreferences()
        flight_conditions.setMach(float(preferences.getDefaultMach()))
    except Exception:
        pass
    cp = _compute_cp(BarrowmanCalculator(), configuration, flight_conditions)

    stage_diameters_m = _stage_bodytube_diameters(rocket)
    reference_diameter_m = max(stage_diameters_m.values(), default=0.0)
    stability_margin = None
    if reference_diameter_m > 0:
        stability_margin = float((cp.x - custom_cg_x_m) / reference_diameter_m)

    stage_masses = _compute_stage_masses(mass_calc, configuration)
    total_mass = float(cg.weight)
    stage_masses_lb = {str(k): _to_pounds(v) for k, v in stage_masses.items()}
    reference_length = float(configuration.getReferenceLength())

    motors_included = False
    if motor_path:
        if expected_motor_mass_kg is None:
            motors_included = True
        else:
            observed_motor_mass_kg = max(0.0, float(cg.weight) - float(base_cg.weight))
            missing_motor_mass_kg = max(0.0, expected_motor_mass_kg - observed_motor_mass_kg)
            motors_included = (
                expected_motor_mass_kg == 0
                or observed_motor_mass_kg >= expected_motor_mass_kg * 0.5
                or missing_motor_mass_kg > 0
            )

    return {
        "cg": {"x": custom_cg_x_m, "y": float(cg.y), "z": float(cg.z), "unit": "m"},
        "cp": {"x": float(cp.x), "y": float(cp.y), "z": float(cp.z), "unit": "m"},
        "total_mass": total_mass,
        "stage_masses": {str(k): v for k, v in stage_masses.items()},
        "stability_margin": stability_margin,
        "cg_in": {"x": _to_inches(custom_cg_x_m), "y": 0.0, "z": 0.0, "unit": "in"},
        "cp_in": {"x": _to_inches(float(cp.x)), "y": 0.0, "z": 0.0, "unit": "in"},
        "total_mass_lb": _to_pounds(total_mass),
        "stage_masses_lb": stage_masses_lb,
        "reference_length_m": reference_length,
        "reference_length_in": _to_inches(reference_length),
        "components": _collect_components(rocket, auto_overrides),
        "material_recommendation": {
            "default": recommended_material,
            "overrides": auto_overrides,
        },
        "material_options": _material_catalog(),
        "motor_mass_kg": desired_motor_mass_kg,
        "motors_included": motors_included,
        "flight_config_id": str(config_id) if config_id is not None else None,
        "use_all_stages": bool(params.get("use_all_stages", True)),
    }


def run_openrocket_core_masscalc(params: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    jar_path = params.get("openrocket_jar") or settings.openrocket_jar
    if not jar_path:
        raise RuntimeError("OPENROCKET_JAR not configured")
    if not os.path.exists(jar_path):
        raise FileNotFoundError(f"OpenRocket jar not found: {jar_path}")

    classpath = _build_classpath(jar_path)
    _ensure_jvm(classpath)

    rocket_path = params.get("rocket_path")
    if not rocket_path or not os.path.exists(rocket_path):
        raise FileNotFoundError("rocket_path not found")

    motor_path = params.get("motor_path")
    if motor_path and not os.path.exists(motor_path):
        raise FileNotFoundError("motor_path not found")

    try:
        jpype.JClass("info.openrocket.core.startup.Application")
        core_api = True
    except Exception:
        core_api = False

    if core_api:
        _ensure_openrocket_core_initialized()

        Application = jpype.JClass("info.openrocket.core.startup.Application")
        GeneralRocketLoader = jpype.JClass("info.openrocket.core.file.GeneralRocketLoader")
        GeneralMotorLoader = jpype.JClass("info.openrocket.core.file.motor.GeneralMotorLoader")
        FileInputStream = jpype.JClass("java.io.FileInputStream")
        File = jpype.JClass("java.io.File")
        MotorDatabase = jpype.JClass("info.openrocket.core.database.motor.MotorDatabase")

        if motor_path:
            motor_loader = GeneralMotorLoader()
            stream = FileInputStream(motor_path)
            try:
                motors = motor_loader.load(stream, os.path.basename(motor_path))
            finally:
                stream.close()
            if motors.size() == 0:
                raise RuntimeError("No motors found in .eng file")
            motor_db = Application.getInjector().getInstance(MotorDatabase)
            for index in range(int(motors.size())):
                motor_db.addMotor(motors.get(index))

        document = GeneralRocketLoader(File(rocket_path)).load()
        configuration = _select_core_configuration(
            document,
            params.get("flight_config_id"),
            bool(params.get("use_all_stages", True)),
        )

        MassCalculator = jpype.JClass("info.openrocket.core.masscalc.MassCalculator")
        MassCalculationType = jpype.JClass("info.openrocket.core.masscalc.MassCalculation$Type")
        rigid_body = MassCalculator.calculate(MassCalculationType.LAUNCH, configuration, 0.0)
        center = rigid_body.getCM()
        mass_kg = float(rigid_body.getMass())
    else:
        _ensure_openrocket_initialized()

        Application = jpype.JClass("net.sf.openrocket.startup.Application")
        GeneralRocketLoader = jpype.JClass("net.sf.openrocket.file.GeneralRocketLoader")
        GeneralMotorLoader = jpype.JClass("net.sf.openrocket.file.motor.GeneralMotorLoader")
        FileInputStream = jpype.JClass("java.io.FileInputStream")
        File = jpype.JClass("java.io.File")
        MotorDatabase = jpype.JClass("net.sf.openrocket.database.motor.MotorDatabase")

        if motor_path:
            motor_loader = GeneralMotorLoader()
            stream = FileInputStream(motor_path)
            try:
                motors = motor_loader.load(stream, os.path.basename(motor_path))
            finally:
                stream.close()
            if motors.size() == 0:
                raise RuntimeError("No motors found in .eng file")
            motor_db = Application.getInjector().getInstance(MotorDatabase)
            for index in range(int(motors.size())):
                motor_db.addMotor(motors.get(index))

        document = GeneralRocketLoader(File(rocket_path)).load()
        configuration = _select_configuration(
            document,
            params.get("flight_config_id"),
            bool(params.get("use_all_stages", True)),
        )

        MassCalculator = jpype.JClass("net.sf.openrocket.masscalc.MassCalculator")
        MassCalculationType = jpype.JClass("net.sf.openrocket.masscalc.MassCalculation$Type")
        rigid_body = MassCalculator.calculate(MassCalculationType.LAUNCH, configuration, 0.0)
        center = rigid_body.getCM()
        mass_kg = float(rigid_body.getMass())

    return {
        "mass_kg": mass_kg,
        "mass_lb": _to_pounds(mass_kg),
        "cg_m": float(center.x),
        "cg_in": _to_inches(float(center.x)),
    }


def run_openrocket_pipeline(params: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    jar_path = params.get("openrocket_jar") or settings.openrocket_jar
    if not jar_path:
        raise RuntimeError("OPENROCKET_JAR not configured")
    if not os.path.exists(jar_path):
        raise FileNotFoundError(f"OpenRocket jar not found: {jar_path}")

    rocket_path = params.get("rocket_path")
    motor_path = params.get("motor_path")
    if not rocket_path or not os.path.exists(rocket_path):
        raise FileNotFoundError("rocket_path not found")
    if not motor_path or not os.path.exists(motor_path):
        raise FileNotFoundError("motor_path not found")

    motor_mass_kg = params.get("motor_mass_kg")
    motor_length_m = params.get("motor_length_m")

    eng_data: EngMotorDefinition = parse_eng_file(motor_path)
    motor_diameter_m = eng_data.diameter_m
    motor_length_m = eng_data.length_m

    classpath = _build_classpath(jar_path)
    _ensure_jvm(classpath)
    _ensure_openrocket_initialized()

    GeneralRocketLoader = jpype.JClass("net.sf.openrocket.file.GeneralRocketLoader")
    GeneralMotorLoader = jpype.JClass("net.sf.openrocket.file.motor.GeneralMotorLoader")
    BarrowmanCalculator = jpype.JClass("net.sf.openrocket.aerodynamics.BarrowmanCalculator")
    FlightConditions = jpype.JClass("net.sf.openrocket.aerodynamics.FlightConditions")
    FileInputStream = jpype.JClass("java.io.FileInputStream")
    File = jpype.JClass("java.io.File")

    document = GeneralRocketLoader(File(rocket_path)).load()
    rocket = document.getRocket()
    requested_config_id = params.get("flight_config_id")
    default_config_id = _default_motor_config_id(rocket_path)
    configuration = _select_configuration(
        document,
        requested_config_id or default_config_id,
        bool(params.get("use_all_stages", True)),
    )
    config_id = configuration.getFlightConfigurationID()
    motor_mount_ids = _motor_mount_component_ids(rocket_path)

    motor_loader = GeneralMotorLoader()
    normalized_path, temp_path = _normalized_motor_path_for_openrocket(motor_path)
    stream = FileInputStream(normalized_path)
    try:
        motors = motor_loader.load(stream, os.path.basename(normalized_path))
    finally:
        stream.close()
        if temp_path:
            try:
                os.remove(temp_path)
            except Exception:
                pass
    if motors.size() == 0:
        raise RuntimeError("No motors found in .eng file")
    motor = motors.get(0)

    mounts_with_config = _motor_mounts_for_config(rocket, config_id)
    if motor_mount_ids:
        mounts_with_config = [
            (mount, motor)
            for mount, motor in mounts_with_config
            if str(mount.getID()) in motor_mount_ids
        ]
    target_mounts = [mount for mount, _ in mounts_with_config]
    if not target_mounts:
        mounts = _motor_mounts_by_stage(rocket)
        mounts.sort(key=lambda item: item[1])
        if motor_mount_ids:
            target_mounts = [
                mount for mount, _ in mounts if str(mount.getID()) in motor_mount_ids
            ]
        if not target_mounts:
            target_stage = mounts[0][1] if mounts else 0
            target_mounts = [mount for mount, stage in mounts if stage == target_stage]
            if motor_mount_ids:
                target_mounts = [
                    mount for mount in target_mounts if str(mount.getID()) in motor_mount_ids
                ]
        if not target_mounts:
            target_mounts = [mount for mount, _ in mounts]
            if motor_mount_ids:
                target_mounts = [
                    mount for mount in target_mounts if str(mount.getID()) in motor_mount_ids
                ]

    if motor_length_m is None:
        for _, configured_motor in mounts_with_config:
            try:
                if configured_motor is not None:
                    motor_length_m = float(configured_motor.getLength())
                    break
            except Exception:
                continue
    if motor_length_m is None:
        motor_length_m = eng_data.length_m

    eng_motor_mass_kg = eng_data.total_mass_kg
    desired_motor_mass_kg = None
    motor_mass_source = None
    if motor_mass_kg is not None and float(motor_mass_kg) > 0:
        desired_motor_mass_kg = float(motor_mass_kg)
        motor_mass_source = "user"
    elif eng_motor_mass_kg is not None and float(eng_motor_mass_kg) > 0:
        desired_motor_mass_kg = float(eng_motor_mass_kg)
        motor_mass_source = "eng"
    if desired_motor_mass_kg is None:
        raise ValueError("motor_mass_kg is required when .eng mass is unavailable")

    extra_motor_mass_kg = desired_motor_mass_kg
    if eng_motor_mass_kg is not None:
        extra_motor_mass_kg = max(0.0, desired_motor_mass_kg - float(eng_motor_mass_kg))

    include_geometry = bool(params.get("include_geometry", False))
    geometry_updates: list[dict[str, Any]] = []
    for mount in target_mounts:
        update_info = _adjust_motor_geometry(
            mount, float(motor_length_m), float(motor_diameter_m)
        )
        if include_geometry and update_info:
            geometry_updates.append(update_info)

    pressure_pa = params.get("pressure_pa")
    material_mode = params.get("material_mode", "auto")
    material_default = params.get("material_default")
    material_overrides = params.get("material_overrides")
    apply_materials_param = params.get("apply_materials")
    recommended_material = _recommend_material(pressure_pa)
    auto_overrides = None
    if material_mode == "auto":
        auto_overrides = _auto_material_overrides(rocket, pressure_pa)
        if auto_overrides:
            merged_overrides = dict(auto_overrides)
            if material_overrides:
                merged_overrides.update(material_overrides)
            material_overrides = merged_overrides
        if material_default is None and not material_overrides:
            material_default = recommended_material
    if apply_materials_param is None:
        apply_materials = material_mode == "custom"
    else:
        apply_materials = bool(apply_materials_param)
    if apply_materials:
        if material_default or material_overrides:
            _apply_materials(rocket, material_default, material_overrides)

    mass_calc = _launch_mass_calc
    base_cg = mass_calc(configuration)

    for mount in target_mounts:
        _apply_motor_to_mounts(rocket, config_id, motor, float(motor_length_m))
        if extra_motor_mass_kg > 0:
            _add_motor_mass_component(mount, extra_motor_mass_kg)

    try:
        rocket.setSelectedConfiguration(configuration)
    except Exception:
        pass
    configuration = _select_configuration(
        document,
        requested_config_id or default_config_id,
        bool(params.get("use_all_stages", True)),
    )

    target_mount_ids = {str(mount.getID()) for mount in target_mounts} if target_mounts else None
    motor_cg_offset_m = float(params.get("motor_cg_offset_m", 0.34))
    sustainer_motor_mass_kg = params.get("sustainer_motor_mass_kg")
    booster_motor_mass_kg = params.get("booster_motor_mass_kg")
    custom_cg_x_m, _ = _compute_custom_cg_from_xml(
        rocket_path,
        float(sustainer_motor_mass_kg) if sustainer_motor_mass_kg is not None else None,
        float(booster_motor_mass_kg) if booster_motor_mass_kg is not None else None,
        target_mount_ids,
        motor_cg_offset_m=motor_cg_offset_m,
    )

    cg = mass_calc(configuration)
    custom_cg_x_m = custom_cg_x_m if custom_cg_x_m is not None else float(cg.x)

    flight_conditions = FlightConditions(configuration)
    flight_conditions.setAOA(0.0)
    try:
        Application = jpype.JClass("net.sf.openrocket.startup.Application")
        preferences = Application.getPreferences()
        flight_conditions.setMach(float(preferences.getDefaultMach()))
    except Exception:
        pass
    cp = _compute_cp(BarrowmanCalculator(), configuration, flight_conditions)

    stage_diameters_m = _stage_bodytube_diameters(rocket)
    reference_diameter_m = max(stage_diameters_m.values(), default=0.0)
    stability_margin = None
    if reference_diameter_m > 0:
        stability_margin = float((cp.x - custom_cg_x_m) / reference_diameter_m)

    expected_motor_mass_kg = float(desired_motor_mass_kg) * max(len(target_mounts), 1)
    observed_motor_mass_kg = max(0.0, float(cg.weight) - float(base_cg.weight))
    missing_motor_mass_kg = 0.0
    if expected_motor_mass_kg > 0 and observed_motor_mass_kg < expected_motor_mass_kg * 0.9:
        missing_motor_mass_kg = max(0.0, expected_motor_mass_kg - observed_motor_mass_kg)
        if missing_motor_mass_kg > 0 and target_mounts:
            per_mount_missing = missing_motor_mass_kg / len(target_mounts)
            before_weight = float(cg.weight)
            for mount in target_mounts:
                _add_motor_mass_component(mount, per_mount_missing)
            try:
                rocket.setSelectedConfiguration(configuration)
            except Exception:
                pass
            configuration = _select_configuration(
                document,
                requested_config_id or default_config_id,
                bool(params.get("use_all_stages", True)),
            )
            cg = mass_calc(configuration)
            if abs(float(cg.weight) - before_weight) < 1e-6:
                for mount in target_mounts:
                    try:
                        parent = mount.getParent()
                    except Exception:
                        parent = None
                    if parent is not None:
                        _add_motor_mass_component(parent, per_mount_missing)
                try:
                    rocket.setSelectedConfiguration(configuration)
                except Exception:
                    pass
                configuration = _select_configuration(
                    document,
                    requested_config_id or default_config_id,
                    bool(params.get("use_all_stages", True)),
                )
                cg = mass_calc(configuration)

    stages = _compute_stage_metrics(
        configuration,
        mass_calc,
        BarrowmanCalculator(),
        flight_conditions,
        stage_diameters=stage_diameters_m,
    )
    for stage in stages:
        diameter_m = stage_diameters_m.get(stage["stage"])
        if diameter_m is not None:
            stage["diameter_m"] = diameter_m
            stage["diameter_in"] = _to_inches(diameter_m)

    observed_motor_mass_kg = max(0.0, float(cg.weight) - float(base_cg.weight))
    observed_motor_mass_kg = max(0.0, float(cg.weight) - float(base_cg.weight))
    missing_motor_mass_kg = max(0.0, expected_motor_mass_kg - observed_motor_mass_kg)
    motors_included = expected_motor_mass_kg == 0 or (
        observed_motor_mass_kg >= expected_motor_mass_kg * 0.5
    ) or missing_motor_mass_kg > 0
    motor_mass_debug = {
        "expected_motor_mass_kg": expected_motor_mass_kg,
        "observed_motor_mass_kg": observed_motor_mass_kg,
        "missing_motor_mass_kg": missing_motor_mass_kg,
        "motor_mount_count": len(target_mounts),
        "base_mass_kg": float(base_cg.weight),
        "final_mass_kg": float(cg.weight),
    }
    return {
        "global": {
            "mass_lb": _to_pounds(float(cg.weight)),
            "cg_in": _to_inches(custom_cg_x_m),
            "cp_in": _to_inches(float(cp.x)),
            "stability_margin": stability_margin,
            "motors_included": motors_included,
        },
        "materials": {
            "recommended": {
                "default": recommended_material,
                "overrides": auto_overrides,
            },
            "options": _material_catalog(),
            "components": _collect_components(rocket, auto_overrides),
        },
        "motor": {
            "name": eng_data.name,
            "diameter_m": eng_data.diameter_m,
            "diameter_in": _to_inches(eng_data.diameter_m),
            "length_m": float(motor_length_m),
            "length_in": _to_inches(float(motor_length_m)),
            "total_impulse_ns": eng_data.total_impulse_ns,
            "burn_time_s": eng_data.burn_time_s,
            "propellant_mass_kg": eng_data.propellant_mass_kg,
            "total_mass_kg": eng_data.total_mass_kg,
            "motor_mass_source": motor_mass_source,
            "thrust_curve": eng_data.thrust_curve,
        },
        "stages": stages,
        "geometry": {
            "motor_length_m": float(motor_length_m),
            "motor_length_in": _to_inches(float(motor_length_m)),
            "mounts": geometry_updates,
            "motor_mass_debug": motor_mass_debug,
        }
        if include_geometry
        else None,
    }
