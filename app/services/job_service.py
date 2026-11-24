from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.job import Job
from app.models.project import Project
from app.models.user import User
from app.services.common import get_owned
from app.workers.executor import get_executor


def ensure_project(db: Session, user: User, project_id: str | None) -> None:
    if project_id:
        get_owned(db, Project, project_id, user.id, "Project")


def create_job(db: Session, user: User, job_type: str, params: dict[str, Any], project_id: str | None = None) -> Job:
    ensure_project(db, user, project_id)
    job = Job(
        user_id=user.id,
        project_id=project_id,
        type=job_type,
        status="queued",
        progress=0.0,
        stage="Queued",
        params=params,
    )
    db.add(job)
    db.flush()
    return job


def get_job(db: Session, user: User, job_id: str, job_type: str | None = None) -> Job:
    job = get_owned(db, Job, job_id, user.id, "Job")
    if job_type is not None and job.type != job_type:
        # A speech job id must not be readable through /transcription etc.
        from app.core.errors import NotFound

        raise NotFound("Job not found.")
    return job


def dispatch(job_id: str) -> None:
    """Hand a *committed* job to the configured executor."""
    get_executor().submit(job_id)
