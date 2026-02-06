from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import platform
import re
import subprocess
from threading import Lock
from typing import Iterable, Optional, Tuple

import jpype
import jpype.imports  # noqa: F401


_JVM_LOCK = Lock()
_HEADLESS_MODULE = None
_PRESET_LOADER = None
_MOTOR_LOADER = None


class OpenRocketRunnerError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenRocketLaunchParams:
    launch_altitude_m: float = 0.0
    wind_speed_m_s: float = 0.0
    temperature_k: float | None = None
    rod_length_m: float = 0.0
    launch_angle_deg: float = 0.0


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_openrocket_jar() -> str:
    override = os.getenv("OPENROCKET_JAR_PATH")
    if override:
        return override
    default_jar = _project_root() / "resources" / "jars" / "OpenRocket-23.09.jar"
    if default_jar.exists():
        return str(default_jar)
    legacy_jar = _project_root() / "resources" / "jars" / "OpenRocket-15.03.jar"
    if legacy_jar.exists():
        return str(legacy_jar)
    raise OpenRocketRunnerError("OpenRocket jar not found")


def _resolve_openrocket_user_dir() -> Path:
    override = os.getenv("OPENROCKET_USER_DIR")
    if override:
        return Path(override)
    return _project_root() / "resources" / "openrocket_user"


def _required_java_major(jar_path: str) -> int:
    name = os.path.basename(jar_path)
    if name.startswith("OpenRocket-23") or name.startswith("OpenRocket-24"):
        return 17
    return 8


def _parse_java_major(version: str) -> Optional[int]:
    if not version:
        return None
    match = re.search(r"(\d+)", version)
    if not match:
        return None
    major = int(match.group(1))
    if major == 1:
        match = re.search(r"1\.(\d+)", version)
        if match:
            return int(match.group(1))
    return major


def _java_home_version(java_home: Path) -> Optional[int]:
    release_file = java_home / "release"
    if not release_file.exists():
        return None
    try:
        content = release_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for line in content.splitlines():
        if line.startswith("JAVA_VERSION="):
            value = line.split("=", 1)[1].strip().strip('"')
            return _parse_java_major(value)
    return None


def _candidate_java_homes(required_major: int) -> list[Path]:
    candidates: list[Path] = []
    for env_key in ("OPENROCKET_JAVA_HOME", "JAVA_HOME"):
        env_value = os.getenv(env_key)
        if env_value:
            candidates.append(Path(env_value))

    system = platform.system().lower()
    if system == "darwin":
        try:
            result = subprocess.run(
                ["/usr/libexec/java_home", "-v", str(required_major)],
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                path = result.stdout.strip()
                if path:
                    candidates.append(Path(path))
        except OSError:
            pass
        candidates.extend(
            Path("/Library/Java/JavaVirtualMachines").glob("*/Contents/Home")
        )
    elif system == "linux":
        candidates.extend(Path("/usr/lib/jvm").glob("*"))

    filtered: list[Tuple[int, Path]] = []
    for candidate in candidates:
        version = _java_home_version(candidate)
        if version is None:
            continue
        if version >= required_major:
            filtered.append((version, candidate))
    filtered.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in filtered]


def _jvm_library_path(java_home: Path) -> Optional[str]:
    system = platform.system().lower()
    if system == "darwin":
        candidate = java_home / "lib" / "server" / "libjvm.dylib"
    elif system == "windows":
        candidate = java_home / "bin" / "server" / "jvm.dll"
    else:
        candidate = java_home / "lib" / "server" / "libjvm.so"
    return str(candidate) if candidate.exists() else None


def _ensure_jvm() -> None:
    if jpype.isJVMStarted():
        return
    with _JVM_LOCK:
        if jpype.isJVMStarted():
            return
        jar_path = _resolve_openrocket_jar()
        if not os.path.exists(jar_path):
            raise OpenRocketRunnerError(f"OpenRocket jar missing: {jar_path}")
        user_dir = _resolve_openrocket_user_dir()
        prefs_dir = user_dir / "prefs"
        try:
            user_dir.mkdir(parents=True, exist_ok=True)
            (user_dir / "tmp").mkdir(parents=True, exist_ok=True)
            prefs_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OpenRocketRunnerError(
                f"OpenRocket user dir not writable: {user_dir}"
            ) from exc
        jvm_opts = [
            "-Djava.awt.headless=true",
            f"-Duser.home={user_dir}",
            f"-Dopenrocket.userdir={user_dir}",
            f"-Djava.io.tmpdir={user_dir / 'tmp'}",
            f"-Djava.util.prefs.userRoot={prefs_dir}",
            f"-Djava.util.prefs.systemRoot={prefs_dir / 'system'}",
        ]
        required_major = _required_java_major(jar_path)
        jvm_path = None
        for candidate in _candidate_java_homes(required_major):
            jvm_path = _jvm_library_path(candidate)
            if jvm_path:
                break
        try:
            if jvm_path:
                jpype.startJVM(
                    jvm_path,
                    *jvm_opts,
                    classpath=[jar_path],
                    convertStrings=True,
                )
            else:
                jpype.startJVM(
                    *jvm_opts,
                    classpath=[jar_path],
                    convertStrings=True,
                )
        except Exception as exc:
            raise OpenRocketRunnerError(
                "Failed to start JVM for OpenRocket. "
                "Install Java 17+ and/or set OPENROCKET_JAVA_HOME."
            ) from exc


def _ensure_openrocket_initialized() -> None:
    _ensure_jvm()
    try:
        Application = jpype.JClass("net.sf.openrocket.startup.Application")
    except Exception as exc:
        message = str(exc)
        if "UnsupportedClassVersionError" in message:
            raise OpenRocketRunnerError(
                "OpenRocket 23.09 requires Java 17+. "
                "Install a Java 17 runtime and set OPENROCKET_JAVA_HOME."
            ) from exc
        raise
    if Application.getInjector() is not None:
        return
    try:
        SwingStartup = jpype.JClass("net.sf.openrocket.startup.SwingStartup")
        SwingStartup.initializeLogging()
    except Exception:
        pass
    CoreServicesModule = jpype.JClass("net.sf.openrocket.utils.CoreServicesModule")
    PluginModule = jpype.JClass("net.sf.openrocket.plugin.PluginModule")
    Guice = jpype.JClass("com.google.inject.Guice")
    Modules = jpype.JClass("com.google.inject.util.Modules")
    headless_module = _ensure_headless_module()
    base = Modules.override(CoreServicesModule())
    base = base.with_(headless_module)
    injector = Guice.createInjector(base, PluginModule())
    Application.setInjector(injector)
    _start_headless_loaders()


def _ensure_headless_module():
    global _HEADLESS_MODULE
    if _HEADLESS_MODULE is not None:
        return _HEADLESS_MODULE

    ComponentPresetDatabaseLoader = jpype.JClass(
        "net.sf.openrocket.database.ComponentPresetDatabaseLoader"
    )
    MotorDatabaseLoader = jpype.JClass("net.sf.openrocket.database.MotorDatabaseLoader")
    BlockingComponentPresetDatabaseProvider = jpype.JClass(
        "net.sf.openrocket.startup.providers.BlockingComponentPresetDatabaseProvider"
    )
    BlockingMotorDatabaseProvider = jpype.JClass(
        "net.sf.openrocket.startup.providers.BlockingMotorDatabaseProvider"
    )
    ComponentPresetDao = jpype.JClass("net.sf.openrocket.database.ComponentPresetDao")
    ThrustCurveMotorSetDatabase = jpype.JClass(
        "net.sf.openrocket.database.motor.ThrustCurveMotorSetDatabase"
    )
    MotorDatabase = jpype.JClass("net.sf.openrocket.database.motor.MotorDatabase")
    Scopes = jpype.JClass("com.google.inject.Scopes")

    preset_loader = ComponentPresetDatabaseLoader()
    motor_loader = MotorDatabaseLoader()
    preset_provider = BlockingComponentPresetDatabaseProvider(preset_loader)
    motor_provider = BlockingMotorDatabaseProvider(motor_loader)

    def configure(binder):
        binder.bind(ComponentPresetDao).toProvider(preset_provider).in_(Scopes.SINGLETON)
        binder.bind(ThrustCurveMotorSetDatabase).toProvider(motor_provider).in_(
            Scopes.SINGLETON
        )
        binder.bind(MotorDatabase).toProvider(motor_provider).in_(Scopes.SINGLETON)

    _HEADLESS_MODULE = jpype.JProxy("com.google.inject.Module", dict(configure=configure))
    global _PRESET_LOADER, _MOTOR_LOADER
    _PRESET_LOADER = preset_loader
    _MOTOR_LOADER = motor_loader
    return _HEADLESS_MODULE


def _start_headless_loaders() -> None:
    if _PRESET_LOADER is None or _MOTOR_LOADER is None:
        return
    try:
        _PRESET_LOADER.startLoading()
    except Exception:
        pass
    try:
        _MOTOR_LOADER.startLoading()
    except Exception:
        pass


def openrocket_healthcheck() -> dict[str, object]:
    jar_path = _resolve_openrocket_jar()
    required_major = _required_java_major(jar_path)
    try:
        _ensure_openrocket_initialized()
    except Exception as exc:
        return {
            "status": "error",
            "detail": str(exc),
            "required_java_major": required_major,
            "jar_path": jar_path,
        }
    return {
        "status": "ok",
        "required_java_major": required_major,
        "jar_path": jar_path,
    }


def _load_document(ork_path: str):
    _ensure_openrocket_initialized()
    if not os.path.exists(ork_path):
        raise OpenRocketRunnerError(f"ORK file not found: {ork_path}")
    OpenRocketLoader = jpype.JClass(
        "net.sf.openrocket.file.openrocket.importt.OpenRocketLoader"
    )
    DocumentLoadingContext = jpype.JClass("net.sf.openrocket.file.DocumentLoadingContext")
    DatabaseMotorFinder = jpype.JClass("net.sf.openrocket.file.DatabaseMotorFinder")
    OpenRocketDocumentFactory = jpype.JClass(
        "net.sf.openrocket.document.OpenRocketDocumentFactory"
    )
    FileInputStream = jpype.JClass("java.io.FileInputStream")
    loader = OpenRocketLoader()
    context = DocumentLoadingContext()
    try:
        context.setMotorFinder(DatabaseMotorFinder())
    except Exception as exc:
        raise OpenRocketRunnerError(
            "Failed to initialize OpenRocket motor finder for ORK loading."
        ) from exc
    document = OpenRocketDocumentFactory.createNewRocket()
    context.setOpenRocketDocument(document)
    stream = FileInputStream(ork_path)
    try:
        loader.loadFromStream(context, stream, ork_path)
    finally:
        stream.close()
    _select_full_stack_configuration(context.getOpenRocketDocument())
    return context.getOpenRocketDocument()


def _select_full_stack_configuration(document) -> None:
    try:
        rocket = document.getRocket()
        config_count = int(rocket.getFlightConfigurationCount())
        if config_count <= 0:
            return
        max_stage_count = -1
        chosen_id = None
        for idx in range(config_count):
            config = rocket.getFlightConfigurationByIndex(idx)
            if config is None:
                continue
            stage_count = int(config.getActiveStageCount())
            if stage_count > max_stage_count:
                max_stage_count = stage_count
                chosen_id = config.getId()
        if chosen_id is not None:
            rocket.setSelectedConfiguration(chosen_id)
    except Exception:
        pass


def _load_motors_from_eng(eng_path: str):
    _ensure_jvm()
    if not os.path.exists(eng_path):
        raise OpenRocketRunnerError(f"Motor file not found: {eng_path}")
    GeneralMotorLoader = jpype.JClass("net.sf.openrocket.file.motor.GeneralMotorLoader")
    FileInputStream = jpype.JClass("java.io.FileInputStream")
    loader = GeneralMotorLoader()
    stream = FileInputStream(eng_path)
    try:
        builders = loader.load(stream, os.path.basename(eng_path))
    finally:
        stream.close()
    motors = []
    for builder in list(builders):
        motors.append(builder.build())
    if not motors:
        raise OpenRocketRunnerError(f"No motors parsed from {eng_path}")
    return motors


def _motor_mounts_with_configs(document):
    rocket = document.getRocket()
    flight_config = rocket.getSelectedConfiguration()
    components = list(flight_config.getAllComponents())
    MotorConfiguration = jpype.JClass("net.sf.openrocket.motor.MotorConfiguration")
    mounts = []
    for component in components:
        if not component.isMotorMount():
            continue
        mount = component
        config_id = flight_config.getId()
        config = mount.getMotorConfig(config_id)
        if config is None:
            config = MotorConfiguration(mount, config_id)
            mount.setMotorConfig(config, config_id)
        x_pos = float(config.getX())
        mounts.append((x_pos, mount, config))
    mounts.sort(key=lambda item: item[0], reverse=True)
    return mounts


def _apply_stage_separation(document, stage_count: int, separation_delay_s: float) -> None:
    if stage_count <= 1:
        return
    rocket = document.getRocket()
    SeparationEvent = jpype.JClass(
        "net.sf.openrocket.rocketcomponent.StageSeparationConfiguration$SeparationEvent"
    )
    for stage in list(rocket.getStageList()):
        if stage.getStageNumber() <= 0:
            continue
        config = stage.getSeparationConfiguration()
        config.setSeparationEvent(SeparationEvent.BURNOUT)
        config.setSeparationDelay(float(separation_delay_s))


def _apply_ignition_overrides(
    document,
    stage_count: int,
    ignition_delay_s: float,
) -> None:
    mounts = _motor_mounts_with_configs(document)
    if not mounts:
        raise OpenRocketRunnerError("No motor mounts found in ORK")
    IgnitionEvent = jpype.JClass("net.sf.openrocket.motor.IgnitionEvent")
    if stage_count <= 1:
        for _, _, config in mounts:
            config.setIgnitionEvent(IgnitionEvent.LAUNCH)
            config.setIgnitionDelay(0.0)
        return
    for idx, (_, _, config) in enumerate(mounts):
        if idx == 0:
            config.setIgnitionEvent(IgnitionEvent.LAUNCH)
            config.setIgnitionDelay(0.0)
        elif idx == 1:
            config.setIgnitionEvent(IgnitionEvent.BURNOUT)
            config.setIgnitionDelay(float(ignition_delay_s))
        else:
            config.setIgnitionEvent(IgnitionEvent.LAUNCH)
            config.setIgnitionDelay(0.0)


def _assign_motors(
    document,
    motor_paths: Iterable[str],
    stage_count: int,
    ignition_delay_s: float,
    separation_delay_s: float,
) -> None:
    motors = []
    for path in motor_paths:
        motors.extend(_load_motors_from_eng(path))
    if not motors:
        raise OpenRocketRunnerError("No motors available for assignment")
    mounts = _motor_mounts_with_configs(document)
    if not mounts:
        raise OpenRocketRunnerError("No motor mounts found in ORK")

    if stage_count <= 1 or len(motors) == 1:
        for _, _, config in mounts:
            config.setMotor(motors[0])
    else:
        primary_motor = motors[0]
        secondary_motor = motors[1] if len(motors) > 1 else motors[0]
        for idx, (_, _, config) in enumerate(mounts):
            if idx == 0:
                config.setMotor(primary_motor)
            elif idx == 1:
                config.setMotor(secondary_motor)
            else:
                config.setMotor(primary_motor)
    _apply_ignition_overrides(document, stage_count, ignition_delay_s)
    _apply_stage_separation(document, stage_count, separation_delay_s)


def _prepare_simulation(document, launch_params: OpenRocketLaunchParams):
    Simulation = jpype.JClass("net.sf.openrocket.document.Simulation")
    simulations = document.getSimulations()
    if simulations is not None and simulations.size() > 0:
        sim = simulations.get(0)
    else:
        sim = Simulation(document, document.getRocket())
        document.addSimulation(sim)
    options = sim.getOptions()
    options.setLaunchAltitude(float(launch_params.launch_altitude_m))
    options.setWindSpeedAverage(float(launch_params.wind_speed_m_s))
    options.setLaunchRodLength(float(launch_params.rod_length_m))
    options.setLaunchRodAngle(float(launch_params.launch_angle_deg))
    if launch_params.temperature_k is not None:
        options.setISAAtmosphere(False)
        options.setLaunchTemperature(float(launch_params.temperature_k))
    return sim


def run_openrocket_simulation(params: dict[str, object]) -> dict[str, float]:
    ork_path = str(params.get("rocket_path") or params.get("ork_path") or "")
    if not ork_path:
        raise OpenRocketRunnerError("rocket_path is required")
    motor_paths = params.get("motor_paths") or []
    if isinstance(motor_paths, str):
        motor_paths = [motor_paths]
    stage_count = int(params.get("stage_count") or len(motor_paths) or 1)
    ignition_delay_s = float(params.get("ignition_delay_s") or 0.0)
    separation_delay_s = float(params.get("separation_delay_s") or 0.0)
    launch_params = OpenRocketLaunchParams(
        launch_altitude_m=float(params.get("launch_altitude_m") or 0.0),
        wind_speed_m_s=float(params.get("wind_speed_m_s") or 0.0),
        temperature_k=(
            float(params["temperature_k"]) if params.get("temperature_k") is not None else None
        ),
        rod_length_m=float(params.get("rod_length_m") or 0.0),
        launch_angle_deg=float(params.get("launch_angle_deg") or 0.0),
    )

    document = _load_document(ork_path)
    if motor_paths:
        _assign_motors(
            document=document,
            motor_paths=motor_paths,
            stage_count=stage_count,
            ignition_delay_s=ignition_delay_s,
            separation_delay_s=separation_delay_s,
        )
    else:
        _apply_ignition_overrides(document, stage_count, ignition_delay_s)
        _apply_stage_separation(document, stage_count, separation_delay_s)

    sim = _prepare_simulation(document, launch_params)
    sim.simulate()
    data = sim.getSimulatedData()
    return {
        "apogee_m": float(data.getMaxAltitude()),
        "max_velocity_m_s": float(data.getMaxVelocity()),
        "max_mach": float(data.getMaxMachNumber()),
        "time_to_apogee_s": float(data.getTimeToApogee()),
        "flight_time_s": float(data.getFlightTime()),
    }


def run_openrocket_core_masscalc(params: dict[str, object]) -> dict[str, float]:
    ork_path = str(params.get("rocket_path") or params.get("ork_path") or "")
    if not ork_path:
        raise OpenRocketRunnerError("rocket_path is required")
    motor_path = params.get("motor_path")
    document = _load_document(ork_path)
    if motor_path:
        _assign_motors(
            document=document,
            motor_paths=[str(motor_path)],
            stage_count=1,
            ignition_delay_s=0.0,
            separation_delay_s=0.0,
        )
    rocket = document.getRocket()
    rocket.update()
    return {"mass_kg": float(rocket.getMass())}


def run_openrocket_geometry(params: dict[str, object]) -> dict[str, float]:
    ork_path = str(params.get("rocket_path") or params.get("ork_path") or "")
    if not ork_path:
        raise OpenRocketRunnerError("rocket_path is required")
    document = _load_document(ork_path)
    rocket = document.getRocket()
    rocket.update()
    length_m = float(rocket.getLength())
    diameter_m = float(rocket.getBoundingRadius()) * 2.0
    return {"length_m": length_m, "diameter_m": diameter_m}
