import time

from app.worker.celery_app import celery_app


@celery_app.task
def long_running_task(param: int) -> str:
    time.sleep(10)
    return f"Proceed {param} successfully!"


@celery_app.task
def detect_objects_for_slot():
    return
