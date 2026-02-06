from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.v1.schemas import OrkUploadResponse
from app.engine.openrocket.runner import openrocket_healthcheck
from app.ork.storage import save_uploaded_ork

router = APIRouter(tags=["ork"])


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


@router.get("/ork/health")
def ork_health():
    return openrocket_healthcheck()
