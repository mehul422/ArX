import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routes_optimization import router as optimization_router
from app.api.v1.routes_simulation import router as simulation_router
from app.core.config import get_settings
from app.db.queries import create_jobs_table

logger = logging.getLogger("arx.backend")

app = FastAPI(title="ArX Backend", version="0.1.0")
settings = get_settings()

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


@app.on_event("startup")
def on_startup():
    try:
        create_jobs_table()
        logger.info("jobs table ensured")
    except Exception as exc:  # pragma: no cover - surfaced during startup
        logger.exception("failed to initialize database: %s", exc)
        raise


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled error: %s", exc)
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


app.include_router(simulation_router, prefix="/api/v1")
app.include_router(optimization_router, prefix="/api/v1")
