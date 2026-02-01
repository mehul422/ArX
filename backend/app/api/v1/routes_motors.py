from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.v1.schemas import MotorInfo, MotorUploadResponse
from app.api.v1.schemas_openrocket_like import MotorImportResponseSchema
from app.engine.openrocket_like.importers.service import MotorImportService
from app.motors.storage import (
    list_bundled_motors,
    list_uploaded_motors,
    resolve_motor_path,
    save_uploaded_motor,
)

router = APIRouter(tags=["motors"])


@router.get("/motors", response_model=list[MotorInfo])
def list_motors():
    return [*list_bundled_motors(), *list_uploaded_motors()]


@router.post("/motors/upload", response_model=MotorUploadResponse)
def upload_motor(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith((".eng", ".rse")):
        raise HTTPException(status_code=400, detail="only .eng or .rse files are supported")
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    info = save_uploaded_motor(file.filename, content)
    return MotorUploadResponse(
        motor_id=info.motor_id, filename=info.filename, source="uploaded"
    )


@router.post("/motors/import", response_model=MotorImportResponseSchema)
def import_motor(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith((".eng", ".rse")):
        raise HTTPException(status_code=400, detail="only .eng or .rse files are supported")
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    info = save_uploaded_motor(file.filename, content)
    path = resolve_motor_path("uploaded", info.motor_id)
    service = MotorImportService()
    result = service.import_file(path)
    return MotorImportResponseSchema(record=result.record.__dict__, warnings=result.warnings)
