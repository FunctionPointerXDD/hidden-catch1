"""Entry point kept for ``celery -A app.celery_app worker``.

Re-exports the single Celery application defined in ``app.worker.celery_app``
so that the producer (FastAPI) and the consumer (worker) share one instance
and one configuration.
"""

from app.worker.celery_app import celery_app

__all__ = ["celery_app"]
