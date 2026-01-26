import os
from typing import Any

import jpype

from app.core.config import get_settings


def _ensure_jvm(classpath: str) -> None:
    if jpype.isJVMStarted():
        return
    jpype.startJVM(classpath=[classpath])


def run_openrocket_simulation(params: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    jar_path = params.get("openrocket_jar") or settings.openrocket_jar
    if not jar_path:
        raise RuntimeError("OPENROCKET_JAR not configured")
    if not os.path.exists(jar_path):
        raise FileNotFoundError(f"OpenRocket jar not found: {jar_path}")

    _ensure_jvm(jar_path)

    # Integration placeholder: use JPype to load Java classes when entrypoint is known.
    return {
        "status": "ok",
        "jar_loaded": True,
        "note": "OpenRocket integration stub; configure entrypoint to run simulations.",
        "params": params,
    }
