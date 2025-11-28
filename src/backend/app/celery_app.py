from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "hidden_catch",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    enable_utc=True,
)

# Auto-discover tasks from app.worker.tasks module
celery_app.autodiscover_tasks(["app.worker"])
