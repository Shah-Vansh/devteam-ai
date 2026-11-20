from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_manager, get_session
from app.api.schemas import ProjectCreate, ProjectDetail, ProjectOut, RunStarted
from app.db.models import Project
from app.services.errors import not_found
from app.services.run_manager import RunManager

router = APIRouter(prefix="/api/projects", tags=["projects"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, session: SessionDep) -> ProjectOut:
    project = Project(name=body.name.strip(), requirement=body.requirement.strip())
    session.add(project)
    session.commit()  # before responding; see get_session
    return ProjectOut.model_validate(project)


@router.get("")
def list_projects(session: SessionDep) -> list[ProjectOut]:
    projects = session.scalars(select(Project).order_by(Project.created_at.desc())).all()
    return [ProjectOut.model_validate(p) for p in projects]


@router.get("/{project_id}")
def get_project(project_id: str, session: SessionDep) -> ProjectDetail:
    project = session.get(Project, project_id)
    if project is None:
        raise not_found("project", project_id)
    return ProjectDetail.model_validate(project)


@router.post("/{project_id}/runs", status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    project_id: str, manager: Annotated[RunManager, Depends(get_manager)]
) -> RunStarted:
    """Accepted: the run continues in the background. Follow it with
    GET /api/runs/{run_id} or the event stream."""
    run = manager.start_run(project_id)
    return RunStarted(run_id=run.id, status=run.status)
