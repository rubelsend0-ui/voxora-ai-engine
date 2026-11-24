from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, pagination
from app.models.user import User
from app.schemas.common import Page
from app.schemas.job import JobOut
from app.schemas.misc import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import project_service

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.post("", response_model=ProjectOut, status_code=201, summary="Create a project")
def create_project(
    body: ProjectCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProjectOut:
    project = project_service.create_project(db, user, body.name, body.description)
    db.commit()
    return ProjectOut.from_project(project)


@router.get("", response_model=Page[ProjectOut], summary="List your projects")
def list_projects(
    page: tuple[int, int] = Depends(pagination), user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> Page[ProjectOut]:
    limit, offset = page
    rows, total = project_service.list_projects(db, user, limit, offset)
    return Page[ProjectOut](items=[ProjectOut.from_project(p) for p in rows], total=total, limit=limit, offset=offset)


@router.get("/{project_id}", response_model=ProjectOut, summary="Get a project")
def get_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProjectOut:
    return ProjectOut.from_project(project_service.get_project(db, user, project_id))


@router.patch("/{project_id}", response_model=ProjectOut, summary="Update a project")
def update_project(
    project_id: str, body: ProjectUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProjectOut:
    project = project_service.update_project(db, user, project_id, body.name, body.description)
    db.commit()
    return ProjectOut.from_project(project)


@router.delete("/{project_id}", status_code=204, response_class=Response, summary="Delete a project (jobs/files are kept)")
def delete_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> Response:
    project_service.delete_project(db, user, project_id)
    db.commit()
    return Response(status_code=204)


@router.get("/{project_id}/jobs", response_model=Page[JobOut], summary="List the jobs in a project")
def project_jobs(
    project_id: str,
    page: tuple[int, int] = Depends(pagination),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Page[JobOut]:
    limit, offset = page
    rows, total = project_service.list_project_jobs(db, user, project_id, limit, offset)
    return Page[JobOut](items=[JobOut.from_job(j) for j in rows], total=total, limit=limit, offset=offset)
