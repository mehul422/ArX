import os
import re
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    env: str
    postgres_dsn: str
    redis_url: str
    jar_dir: str
    openrocket_jar: str
    motors_dir: str
    motor_upload_dir: str
    cors_origins: list[str]
    celery_task_soft_time_limit: int
    celery_task_time_limit: int


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return ["*"]
    return [item.strip() for item in value.split(",") if item.strip()]


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _openrocket_version_key(name: str) -> tuple[int, ...] | None:
    match = re.search(r"OpenRocket-(\d+)\.(\d+)", name)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _latest_openrocket_jar(jar_dir: str) -> str | None:
    try:
        entries = os.listdir(jar_dir)
    except FileNotFoundError:
        return None
    candidates: list[tuple[tuple[int, ...], str]] = []
    for entry in entries:
        if not entry.lower().endswith(".jar"):
            continue
        version_key = _openrocket_version_key(entry)
        if version_key:
            candidates.append((version_key, os.path.join(jar_dir, entry)))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    base_dir = _project_root()
    env = os.getenv("ENV", "development")
    postgres_dsn = os.getenv("POSTGRES_DSN", "")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    jar_dir = os.getenv("JAR_DIR", "resources/jars")
    if not os.path.isabs(jar_dir):
        jar_dir = os.path.join(base_dir, jar_dir)
    openrocket_jar = os.getenv("OPENROCKET_JAR")
    if openrocket_jar and not os.path.isabs(openrocket_jar):
        openrocket_jar = os.path.join(base_dir, openrocket_jar)
    if not openrocket_jar:
        openrocket_jar = _latest_openrocket_jar(jar_dir) or ""
    motors_dir = os.getenv("MOTORS_DIR", "resources/motors")
    if not os.path.isabs(motors_dir):
        motors_dir = os.path.join(base_dir, motors_dir)
    motor_upload_dir = os.getenv(
        "MOTOR_UPLOAD_DIR", "resources/motors/uploads"
    )
    if not os.path.isabs(motor_upload_dir):
        motor_upload_dir = os.path.join(base_dir, motor_upload_dir)
    cors_origins = _split_csv(os.getenv("CORS_ORIGINS"))
    celery_task_soft_time_limit = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "300"))
    celery_task_time_limit = int(os.getenv("CELERY_TASK_TIME_LIMIT", "600"))

    return Settings(
        env=env,
        postgres_dsn=postgres_dsn,
        redis_url=redis_url,
        jar_dir=jar_dir,
        openrocket_jar=openrocket_jar,
        motors_dir=motors_dir,
        motor_upload_dir=motor_upload_dir,
        cors_origins=cors_origins,
        celery_task_soft_time_limit=celery_task_soft_time_limit,
        celery_task_time_limit=celery_task_time_limit,
    )
