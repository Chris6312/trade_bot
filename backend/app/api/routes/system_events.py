from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.models.core import SystemEvent
from backend.app.schemas.core import SystemEventCreate, SystemEventRead

router = APIRouter(prefix="/system-events", tags=["system-events"])


@router.post("", response_model=SystemEventRead, status_code=201)
def create_system_event(payload: SystemEventCreate, db: Session = Depends(get_db)) -> SystemEventRead:
    record = SystemEvent(**payload.model_dump())
    db.add(record)
    db.commit()
    db.refresh(record)
    return SystemEventRead.model_validate(record)
