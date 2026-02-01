from __future__ import annotations

import os
from typing import Any


def openmotor_motorlib_version() -> dict[str, Any]:
    return {
        "version": os.getenv("OPENMOTOR_VERSION", "unknown"),
        "commit": os.getenv("OPENMOTOR_COMMIT"),
        "source": "third_party/openmotor_src",
    }


def trajectory_engine_version() -> dict[str, Any]:
    return {"id": "internal_v1"}
