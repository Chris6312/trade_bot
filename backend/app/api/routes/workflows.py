from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.models.core import WorkflowRun, WorkflowStageStatus
from backend.app.schemas.core import (
    WorkflowRunCreate,
    WorkflowRunRead,
    WorkflowStageCreate,
    WorkflowStageRead,
)

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("/runs", response_model=WorkflowRunRead, status_code=201)
def create_workflow_run(payload: WorkflowRunCreate, db: Session = Depends(get_db)) -> WorkflowRunRead:
    record = WorkflowRun(
        workflow_name=payload.workflow_name,
        status=payload.status,
        trigger_source=payload.trigger_source,
        notes=payload.notes,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return WorkflowRunRead.model_validate(record)


@router.get("/runs/{run_id}", response_model=WorkflowRunRead)
def get_workflow_run(run_id: int, db: Session = Depends(get_db)) -> WorkflowRunRead:
    record = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).one_or_none()

    if record is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    return WorkflowRunRead.model_validate(record)


@router.post("/runs/{run_id}/stages", response_model=WorkflowStageRead, status_code=201)
def create_workflow_stage(
    run_id: int,
    payload: WorkflowStageCreate,
    db: Session = Depends(get_db),
) -> WorkflowStageRead:
    run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).one_or_none()

    if run is None:
        raise HTTPException(status_code=404, detail="Workflow run not found")

    stage = WorkflowStageStatus(
        workflow_run_id=run_id,
        stage_name=payload.stage_name,
        status=payload.status,
        details=payload.details,
        completed_at=payload.completed_at,
    )
    db.add(stage)

    if payload.status.lower() in {"completed", "complete", "done"} and run.completed_at is None:
        run.completed_at = payload.completed_at or datetime.now(timezone.utc)

    db.commit()
    db.refresh(stage)
    return WorkflowStageRead.model_validate(stage)
