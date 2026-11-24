"""Celery application. Start a worker with::

    celery -A app.workers.celery_app.celery_app worker --loglevel=info --concurrency=1

Keep concurrency at 1 per GPU: model inference is memory-hungry and serialised by locks anyway.
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings

_settings = get_settings()

celery_app = Celery(
    "voxora",
    broker=_settings.effective_celery_broker or "memory://",
    backend=_settings.effective_celery_backend,
)
celery_app.conf.update(
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_serializer="json",
    accept_content=["json"],
    broker_connection_retry_on_startup=True,
    task_default_queue="voxora",
)


@celery_app.task(name="voxora.run_job", bind=False)
def run_job_task(job_id: str) -> None:
    from app.workers.runner import run_job

    run_job(job_id)
