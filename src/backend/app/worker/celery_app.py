"""Single Celery application shared by the API (producer) and the worker."""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "hidden_catch",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    # JSON only: pickle is unnecessary and the payloads are tiny (slot ids).
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Seoul",
    enable_utc=True,
    # Pipeline tasks write their outcome to the database; nobody reads the
    # Celery result, so skip the round-trip to Redis entirely.
    task_ignore_result=True,
    result_expires=3600,
    # A puzzle generation takes tens of seconds and calls paid APIs. Ack only
    # after success so a crashed worker's task is redelivered, and do not
    # prefetch tasks another idle worker process could be running.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=600,
    task_soft_time_limit=540,
    worker_max_tasks_per_child=100,
    broker_connection_retry_on_startup=True,
    imports=("app.worker.tasks",),
)
