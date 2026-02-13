from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.v1.schemas import OrkUploadResponse
from app.engine.openrocket.runner import openrocket_healthcheck
from app.module_r.ork_parser import parse_ork_to_assembly
from app.ork.storage import save_uploaded_ork

router = APIRouter(tags=["ork"])


class OrkParseRequest(BaseModel):
    path: str


class OrkParseResponse(BaseModel):
    assembly: dict
    warnings: list[str]


@router.post("/ork/upload", response_model=OrkUploadResponse)
def upload_ork(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".ork"):
        raise HTTPException(status_code=400, detail="only .ork files are supported")
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    info = save_uploaded_ork(file.filename, content)
    return OrkUploadResponse(
        ork_id=info.ork_id,
        filename=info.filename,
        path=info.path,
    )


@router.post("/ork/parse", response_model=OrkParseResponse)
def parse_ork(request: OrkParseRequest):
    if not request.path:
        raise HTTPException(status_code=400, detail="path is required")
    path = Path(request.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="ORK path not found")
    if path.suffix.lower() != ".ork":
        raise HTTPException(status_code=400, detail="only .ork files are supported")
    try:
        parsed = parse_ork_to_assembly(str(path))
        return OrkParseResponse(
            assembly=parsed.assembly.model_dump(mode="json"),
            warnings=parsed.warnings,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to parse ORK: {exc}") from exc


@router.get("/ork/health")
def ork_health():
    return openrocket_healthcheck()
