from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from app.api.v1.schemas import V1Error, V1JobResponse
from app.api.v1.units import convert_mass_length_payload


def compute_inputs_hash(payload: dict[str, Any]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_v1_job_response(
    job: dict[str, Any],
    job_kind: Literal["simulate", "mission_target"],
) -> V1JobResponse:
    error = None
    if job.get("error"):
        error = V1Error(code="job_failed", message=str(job["error"]))
    params = job.get("params", {})
    result = job.get("result")
    if job_kind == "mission_target":
        params = convert_mass_length_payload(params)
        result = convert_mass_length_payload(result) if result is not None else None
    return V1JobResponse(
        api_version="v1",
        job_kind=job_kind,
        id=job["id"],
        status=job["status"],
        params=params,
        result=result,
        error=error,
        created_at=job["created_at"],
        updated_at=job["updated_at"],
        type=job_kind,
    )
