import os

from fastapi import APIRouter, HTTPException

from app.api.v1.schemas import V1OrkToRktRequest, V1OrkToRktResponse
from app.engine.integration import ork_to_rkt

router = APIRouter(tags=["integration"])


@router.post("/integrate/ork-to-rkt", response_model=V1OrkToRktResponse)
def integrate_ork_to_rkt(request: V1OrkToRktRequest):
    if not os.path.isabs(request.ork_path):
        raise HTTPException(status_code=400, detail="ork_path must be absolute")
    if not os.path.exists(request.ork_path):
        raise HTTPException(status_code=404, detail="ork file not found")
    if request.eng_path:
        if not os.path.isabs(request.eng_path):
            raise HTTPException(status_code=400, detail="eng_path must be absolute")
        if not os.path.exists(request.eng_path):
            raise HTTPException(status_code=404, detail="eng file not found")
    result = ork_to_rkt(
        ork_path=request.ork_path,
        eng_path=request.eng_path,
        output_dir=request.output_dir,
        rkt_filename=request.rkt_filename,
    )
    return V1OrkToRktResponse(**result)
