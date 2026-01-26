import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Settings:
    env: str
    postgres_dsn: str
    redis_url: str
    jar_dir: str
    openrocket_jar: str
    cors_origins: list[str]
    celery_task_soft_time_limit: int
    celery_task_time_limit: int


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return ["*"]
    return [item.strip() for item in value.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    env = os.getenv("ENV", "development")
    postgres_dsn = os.getenv("POSTGRES_DSN", "")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    jar_dir = os.getenv("JAR_DIR", "backend/resources/jars")
    openrocket_jar = os.getenv("OPENROCKET_JAR", "")
    cors_origins = _split_csv(os.getenv("CORS_ORIGINS"))
    celery_task_soft_time_limit = int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "300"))
    celery_task_time_limit = int(os.getenv("CELERY_TASK_TIME_LIMIT", "600"))

    return Settings(
        env=env,
        postgres_dsn=postgres_dsn,
        redis_url=redis_url,
        jar_dir=jar_dir,
        openrocket_jar=openrocket_jar,
        cors_origins=cors_origins,
        celery_task_soft_time_limit=celery_task_soft_time_limit,
        celery_task_time_limit=celery_task_time_limit,
    )
