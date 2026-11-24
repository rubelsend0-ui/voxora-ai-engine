from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed
from app.models.job import Job
from app.models.project import Project
from app.models.user import User
from app.services.common import get_owned, paginate
from app.utils.ids import utcnow


def create_project(db: Session, user: User, name: str, description: str | None) -> Project:
    project = Project(user_id=user.id, name=name.strip(), description=(description or "").strip() or None)
    if not project.name:
        raise ValidationFailed("name must not be empty.", details={"field": "name"})
    db.add(project)
    db.flush()
    return project


def list_projects(db: Session, user: User, limit: int, offset: int) -> tuple[list[Project], int]:
    return paginate(db, select(Project).where(Project.user_id == user.id), Project.created_at.desc(), limit, offset)


def get_project(db: Session, user: User, project_id: str) -> Project:
    return get_owned(db, Project, project_id, user.id, "Project")


def update_project(db: Session, user: User, project_id: str, name: str | None, description: str | None) -> Project:
    project = get_project(db, user, project_id)
    if name is not None:
        if not name.strip():
            raise ValidationFailed("name must not be empty.", details={"field": "name"})
        project.name = name.strip()
    if description is not None:
        project.description = description.strip() or None
    project.updated_at = utcnow()
    return project


def delete_project(db: Session, user: User, project_id: str) -> None:
    """Deletes the project only; its jobs and files are kept (their project_id becomes NULL)."""
    project = get_project(db, user, project_id)
    for job in db.scalars(select(Job).where(Job.project_id == project.id, Job.user_id == user.id)):
        job.project_id = None
    db.delete(project)


def list_project_jobs(db: Session, user: User, project_id: str, limit: int, offset: int) -> tuple[list[Job], int]:
    get_project(db, user, project_id)
    stmt = select(Job).where(Job.project_id == project_id, Job.user_id == user.id)
    return paginate(db, stmt, Job.created_at.desc(), limit, offset)
