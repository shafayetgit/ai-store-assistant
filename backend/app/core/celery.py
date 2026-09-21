from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "aistore_worker",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.tasks.messenger_tasks",
        "app.tasks.sync_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Periodic / Scheduled Cron Tasks
celery_app.conf.beat_schedule = {
    "sync-store-catalog-periodic": {
        "task": "tasks.sync_store_catalog",
        "schedule": float(settings.STORE_CATALOG_SYNC_INTERVAL_HOURS * 3600.0),
        "args": (100,),
    },
}