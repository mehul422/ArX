import os
import uuid
from dataclasses import dataclass

from app.core.config import get_settings


@dataclass(frozen=True)
class MotorInfo:
    motor_id: str
    filename: str
    source: str


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _safe_filename(filename: str) -> str:
    base = os.path.basename(filename)
    sanitized = "".join(ch for ch in base if ch.isalnum() or ch in ("-", "_", "."))
    if not sanitized:
        return "motor.eng"
    return sanitized


def _legacy_upload_dir(settings) -> str:
    base_dir = os.path.dirname(os.path.dirname(settings.motors_dir))
    return os.path.join(base_dir, "backend", "resources", "motors", "uploads")


def list_bundled_motors() -> list[MotorInfo]:
    settings = get_settings()
    bundled_dir = os.path.join(settings.motors_dir, "bundled")
    if not os.path.isdir(bundled_dir):
        return []
    motors = []
    for name in sorted(os.listdir(bundled_dir)):
        if name.lower().endswith((".eng", ".rse")):
            motors.append(MotorInfo(motor_id=name, filename=name, source="bundled"))
    return motors


def list_uploaded_motors() -> list[MotorInfo]:
    settings = get_settings()
    upload_dir = settings.motor_upload_dir
    legacy_dir = _legacy_upload_dir(settings)
    if not os.path.isdir(upload_dir) and not os.path.isdir(legacy_dir):
        return []
    motors = []
    for directory in [upload_dir, legacy_dir]:
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if name.lower().endswith((".eng", ".rse")):
                motors.append(MotorInfo(motor_id=name, filename=name, source="uploaded"))
    return motors


def save_uploaded_motor(filename: str, content: bytes) -> MotorInfo:
    settings = get_settings()
    _ensure_dir(settings.motor_upload_dir)
    safe_name = _safe_filename(filename)
    motor_id = f"{uuid.uuid4()}__{safe_name}"
    target_path = os.path.join(settings.motor_upload_dir, motor_id)
    with open(target_path, "wb") as handle:
        handle.write(content)
    return MotorInfo(motor_id=motor_id, filename=safe_name, source="uploaded")


def resolve_motor_path(source: str, motor_id: str) -> str:
    settings = get_settings()
    if source == "bundled":
        path = os.path.join(settings.motors_dir, "bundled", motor_id)
    elif source == "uploaded":
        path = os.path.join(settings.motor_upload_dir, motor_id)
        if not os.path.exists(path):
            legacy_path = os.path.join(_legacy_upload_dir(settings), motor_id)
            if os.path.exists(legacy_path):
                path = legacy_path
    else:
        raise ValueError("Unsupported motor source")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Motor file not found: {path}")
    return path
