from fastapi import APIRouter, File, HTTPException, UploadFile

from app.api.v1.schemas import MotorInfo, MotorUploadResponse
from app.motors.storage import (
    list_bundled_motors,
    list_uploaded_motors,
    save_uploaded_motor,
)

router = APIRouter(tags=["motors"])


@router.get("/motors", response_model=list[MotorInfo])
def list_motors():
    return [*list_bundled_motors(), *list_uploaded_motors()]


@router.post("/motors/upload", response_model=MotorUploadResponse)
def upload_motor(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".eng"):
        raise HTTPException(status_code=400, detail="only .eng files are supported")
    content = file.file.read()
    if not content:
        raise HTTPException(status_code=400, detail="uploaded file is empty")
    info = save_uploaded_motor(file.filename, content)
    return MotorUploadResponse(
        motor_id=info.motor_id, filename=info.filename, source="uploaded"
    )
