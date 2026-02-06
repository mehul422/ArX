import os
import uuid
from dataclasses import dataclass

from app.core.config import get_settings


@dataclass(frozen=True)
class OrkInfo:
    ork_id: str
    filename: str
    path: str


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _safe_filename(filename: str) -> str:
    base = os.path.basename(filename)
    sanitized = "".join(ch for ch in base if ch.isalnum() or ch in ("-", "_", ".", " "))
    if not sanitized.lower().endswith(".ork"):
        sanitized = f"{sanitized}.ork" if sanitized else "rocket.ork"
    return sanitized


def save_uploaded_ork(filename: str, content: bytes) -> OrkInfo:
    settings = get_settings()
    _ensure_dir(settings.ork_upload_dir)
    safe_name = _safe_filename(filename)
    ork_id = f"{uuid.uuid4()}__{safe_name}"
    target_path = os.path.join(settings.ork_upload_dir, ork_id)
    with open(target_path, "wb") as handle:
        handle.write(content)
    return OrkInfo(ork_id=ork_id, filename=safe_name, path=target_path)
