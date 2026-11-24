from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.models.job import Job

JobStatus = Literal["queued", "processing", "completed", "failed"]


class JobError(BaseModel):
    code: str
    message: str | None = None


class JobOut(BaseModel):
    job_id: str
    type: str
    status: JobStatus
    progress: float
    stage: str | None = None
    project_id: str | None = None
    result: dict[str, Any] | None = None
    error: JobError | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @classmethod
    def from_job(cls, job: Job, extra_result: dict[str, Any] | None = None) -> JobOut:
        result = dict(job.result) if job.result else None
        if extra_result and job.status == "completed":
            result = {**(result or {}), **extra_result}
        return cls(
            job_id=job.id,
            type=job.type,
            status=job.status,  # type: ignore[arg-type]
            progress=round(float(job.progress or 0.0), 1),
            stage=job.stage,
            project_id=job.project_id,
            result=result,
            error=JobError(code=job.error_code or "UNKNOWN", message=job.error_message)
            if job.status == "failed"
            else None,
            created_at=job.created_at,
            started_at=job.started_at,
            finished_at=job.finished_at,
        )


class JobAccepted(BaseModel):
    job_id: str
    type: str
    status: JobStatus
    status_url: str


def accepted(job: Job, status_url: str) -> JobAccepted:
    return JobAccepted(job_id=job.id, type=job.type, status=job.status, status_url=status_url)  # type: ignore[arg-type]
