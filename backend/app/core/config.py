import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    env: str
    postgres_dsn: str
    redis_url: str
    motors_dir: str
    motor_upload_dir: str
    ork_upload_dir: str
    cors_origins: list[str]
    celery_task_soft_time_limit: int
    celery_task_time_limit: int


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return ["*"]
    return [item.strip() for item in value.split(",") if item.strip()]


def _project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    base_dir = _project_root()
    env = os.getenv("ENV", "development")
    postgres_dsn = os.getenv("POSTGRES_DSN", "")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    motors_dir = os.getenv("MOTORS_DIR", "resources/motors")
    if not os.path.isabs(motors_dir):
        motors_dir = os.path.join(base_dir, motors_dir)
    motor_upload_dir = os.getenv(
        "MOTOR_UPLOAD_DIR", "resources/motors/uploads"
    )
    if not os.path.isabs(motor_upload_dir):
        motor_upload_dir = os.path.join(base_dir, motor_upload_dir)
    ork_upload_dir = os.getenv("ORK_UPLOAD_DIR", "resources/orks/uploads")
    if not os.path.isabs(ork_upload_dir):
        ork_upload_dir = os.path.join(base_dir, ork_upload_dir)
    cors_origins = _split_csv(os.getenv("CORS_ORIGINS"))
    celery_task_soft_time_limit = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "300"))
    celery_task_time_limit = int(os.getenv("CELERY_TASK_TIME_LIMIT", "600"))

    return Settings(
        env=env,
        postgres_dsn=postgres_dsn,
        redis_url=redis_url,
        motors_dir=motors_dir,
        motor_upload_dir=motor_upload_dir,
        ork_upload_dir=ork_upload_dir,
        cors_origins=cors_origins,
        celery_task_soft_time_limit=celery_task_soft_time_limit,
        celery_task_time_limit=celery_task_time_limit,
    )
