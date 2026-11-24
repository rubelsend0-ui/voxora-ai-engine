from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, pagination
from app.models.job import Job
from app.models.user import User
from app.schemas.common import Page
from app.schemas.job import JobOut
from app.services.common import paginate
from app.services.job_service import get_job

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("", response_model=Page[JobOut], summary="List your jobs")
def list_jobs(
    type: Literal["voice_clone", "speech", "transcription", "translation", "dubbing"] | None = None,
    status: Literal["queued", "processing", "completed", "failed"] | None = None,
    project_id: str | None = None,
    page: tuple[int, int] = Depends(pagination),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[JobOut]:
    limit, offset = page
    stmt = select(Job).where(Job.user_id == user.id)
    if type:
        stmt = stmt.where(Job.type == type)
    if status:
        stmt = stmt.where(Job.status == status)
    if project_id:
        stmt = stmt.where(Job.project_id == project_id)
    rows, total = paginate(db, stmt, Job.created_at.desc(), limit, offset)
    return Page[JobOut](items=[JobOut.from_job(j) for j in rows], total=total, limit=limit, offset=offset)


@router.get(
    "/{job_id}",
    response_model=JobOut,
    summary="Get any job: status (queued|processing|completed|failed), progress 0-100, result or error",
)
def get_job_status(job_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> JobOut:
    return JobOut.from_job(get_job(db, user, job_id))
