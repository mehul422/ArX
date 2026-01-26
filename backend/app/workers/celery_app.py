from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "arx_backend",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    task_time_limit=settings.celery_task_time_limit,
    task_track_started=True,
    broker_transport_options={"visibility_timeout": settings.celery_task_time_limit},
)
