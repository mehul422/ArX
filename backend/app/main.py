import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.v1.routes_inputs import router as inputs_router
from app.api.v1.routes_motors import router as motors_router
from app.api.v1.endpoints.motors import router as motors_classify_router
from app.api.v1.routes_optimization import router as optimization_router
from app.api.v1.routes_ork import router as ork_router
from app.core.config import get_settings
from app.db.queries import create_jobs_table, create_user_inputs_table
from app.engine.openmotor_ai.ric_writer import normalize_ric_text

logger = logging.getLogger("arx.backend")

app = FastAPI(title="ArX Backend", version="0.1.0")
settings = get_settings()
downloads_dir = Path(__file__).resolve().parent.parent / "tests"
app.mount("/downloads", StaticFiles(directory=downloads_dir), name="downloads")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/v1/downloads/{file_path:path}")
def download_artifact(file_path: str):
    candidate = (downloads_dir / file_path).resolve()
    downloads_root = downloads_dir.resolve()
    if not str(candidate).startswith(str(downloads_root)):
        raise HTTPException(status_code=400, detail="invalid download path")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    no_cache_headers = {
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "Pragma": "no-cache",
        "Expires": "0",
    }
    if candidate.suffix.lower() == ".ric":
        raw = candidate.read_text(encoding="utf-8")
        normalized = normalize_ric_text(raw)
        return Response(
            content=normalized,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{candidate.name}"',
                **no_cache_headers,
            },
        )
    return FileResponse(
        candidate,
        filename=candidate.name,
        media_type="application/octet-stream",
        headers=no_cache_headers,
    )


@app.on_event("startup")
def on_startup():
    try:
        create_jobs_table()
        create_user_inputs_table()
        logger.info("jobs table ensured")
    except Exception as exc:  # pragma: no cover - surfaced during startup
        logger.exception("failed to initialize database: %s", exc)
        raise


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


app.include_router(optimization_router, prefix="/api/v1")
app.include_router(motors_router, prefix="/api/v1")
app.include_router(inputs_router, prefix="/api/v1")
app.include_router(ork_router, prefix="/api/v1")
app.include_router(motors_classify_router, prefix="/motors", tags=["motors"])