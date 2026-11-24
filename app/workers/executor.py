"""Job executors. Select with ``VOXORA_JOB_BACKEND``: ``local`` | ``celery`` | ``inline``."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from app.core.config import get_settings

log = logging.getLogger("voxora.executor")


class JobExecutor(ABC):
    @abstractmethod
    def submit(self, job_id: str) -> None: ...

    def shutdown(self) -> None:  # pragma: no cover - trivial
        return None


class LocalExecutor(JobExecutor):
    """Thread pool inside the API process. Zero extra infrastructure; single node only."""

    def __init__(self, workers: int) -> None:
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="voxora-job")

    def submit(self, job_id: str) -> None:
        from app.workers.runner import run_job

        self._pool.submit(run_job, job_id)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=False)


class InlineExecutor(JobExecutor):
    """Runs the job synchronously inside the caller. For tests and debugging only."""

    def submit(self, job_id: str) -> None:
        from app.workers.runner import run_job

        run_job(job_id)


class CeleryExecutor(JobExecutor):
    """Publishes the job to Redis; a separate ``celery worker`` process runs it."""

    def submit(self, job_id: str) -> None:
        from app.workers.celery_app import run_job_task

        run_job_task.delay(job_id)


@lru_cache
def get_executor() -> JobExecutor:
    s = get_settings()
    if s.job_backend == "celery":
        return CeleryExecutor()
    if s.job_backend == "inline":
        return InlineExecutor()
    return LocalExecutor(s.local_workers)


def reset_executor() -> None:
    try:
        get_executor().shutdown()
    except Exception:  # pragma: no cover
        pass
    get_executor.cache_clear()
