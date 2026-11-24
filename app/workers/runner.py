"""Job runner shared by every executor (local threads, inline, Celery).

``run_job(job_id)`` moves a job queued -> processing -> completed|failed and records
progress. The same function runs inside Celery workers, so behaviour is identical in
every deployment mode.
"""

from __future__ import annotations

import logging
import shutil
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai_engine.registry import EngineRegistry, get_registry
from app.core.config import Settings, get_settings
from app.core.errors import AIEngineError, VoxoraError
from app.database.session import session_scope
from app.models.job import Job
from app.models.voice import Voice
from app.storage.base import StorageBackend
from app.storage.local import get_storage
from app.utils.ids import utcnow

log = logging.getLogger("voxora.jobs")


@dataclass
class JobContext:
    job_id: str
    user_id: str
    project_id: str | None
    params: dict[str, Any]
    workdir: Path
    settings: Settings
    storage: StorageBackend
    registry: EngineRegistry
    _last: tuple[float, str, float] = field(default=(0.0, "", 0.0), repr=False)

    @contextmanager
    def db(self) -> Iterator[Session]:
        with session_scope() as session:
            yield session

    def progress(self, pct: float, stage: str | None = None) -> None:
        """Persist progress (throttled). Percentages never go backwards."""
        last_pct, last_stage, last_t = self._last
        pct = max(last_pct, min(99.0, float(pct)))
        stage = stage or last_stage
        now = time.monotonic()
        if stage == last_stage and pct - last_pct < 1.0 and now - last_t < 2.0:
            return
        self._last = (pct, stage, now)
        _update(self.job_id, progress=pct, stage=stage[:120])


@dataclass(frozen=True)
class HandlerSpec:
    handler: Callable[[JobContext], dict[str, Any]]
    on_failure: Callable[[JobContext, str, str], None] | None = None


def _handlers() -> dict[str, HandlerSpec]:
    # Imported lazily to avoid import cycles (services import the job helpers).
    from app.services import dubbing_service, speech_service, transcription_service, translation_service, voice_service

    return {
        "voice_clone": HandlerSpec(voice_service.handle_voice_clone, voice_service.on_voice_clone_failed),
        "speech": HandlerSpec(speech_service.handle_speech),
        "transcription": HandlerSpec(transcription_service.handle_transcription),
        "translation": HandlerSpec(translation_service.handle_audio_translation),
        "dubbing": HandlerSpec(dubbing_service.handle_dubbing),
    }


def _update(job_id: str, **fields: Any) -> None:
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is not None:
            for k, v in fields.items():
                setattr(job, k, v)


def run_job(job_id: str) -> None:
    settings = get_settings()
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None or job.status != "queued":
            return  # already handled (e.g. duplicate delivery)
        job.status = "processing"
        job.started_at = utcnow()
        job.stage = "Starting"
        job.progress = 0.0
        jtype, params, user_id, project_id = job.type, dict(job.params or {}), job.user_id, job.project_id

    workdir = settings.tmp_root / job_id
    workdir.mkdir(parents=True, exist_ok=True)
    ctx = JobContext(
        job_id=job_id,
        user_id=user_id,
        project_id=project_id,
        params=params,
        workdir=workdir,
        settings=settings,
        storage=get_storage(),
        registry=get_registry(),
    )
    spec: HandlerSpec | None = None
    try:
        spec = _handlers().get(jtype)
        if spec is None:
            raise AIEngineError(f"Unknown job type '{jtype}'.")
        result = spec.handler(ctx)
        _update(
            job_id,
            status="completed",
            progress=100.0,
            stage="Completed",
            result=result,
            finished_at=utcnow(),
            error_code=None,
            error_message=None,
        )
        log.info("job %s (%s) completed", job_id, jtype)
    except VoxoraError as exc:
        log.warning("job %s (%s) failed: %s %s", job_id, jtype, exc.code, exc.message)
        _fail(ctx, spec, exc.code, exc.message)
    except Exception:
        log.exception("job %s (%s) crashed", job_id, jtype)
        _fail(ctx, spec, "INTERNAL_ERROR", "An unexpected error occurred while processing the job.")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _fail(ctx: JobContext, spec: HandlerSpec | None, code: str, message: str) -> None:
    _update(
        ctx.job_id,
        status="failed",
        stage="Failed",
        error_code=code,
        error_message=message[:2000],
        finished_at=utcnow(),
    )
    if spec is not None and spec.on_failure is not None:
        try:
            spec.on_failure(ctx, code, message)
        except Exception:
            log.exception("on_failure hook failed for job %s", ctx.job_id)


def recover_jobs(submit: Callable[[str], None]) -> None:
    """Local-backend startup: fail jobs a previous process was running, re-queue waiting ones."""
    with session_scope() as db:
        interrupted = db.scalars(select(Job).where(Job.status == "processing")).all()
        for job in interrupted:
            job.status = "failed"
            job.stage = "Failed"
            job.error_code = "JOB_INTERRUPTED"
            job.error_message = "The server restarted while this job was running. Please submit it again."
            job.finished_at = utcnow()
            if job.type == "voice_clone":
                voice = db.get(Voice, (job.params or {}).get("voice_id", ""))
                if voice is not None and voice.status == "processing":
                    voice.status = "failed"
                    voice.error_code = "JOB_INTERRUPTED"
                    voice.error_message = job.error_message
        queued = list(db.scalars(select(Job.id).where(Job.status == "queued").order_by(Job.created_at)))
    for job_id in queued:
        submit(job_id)
