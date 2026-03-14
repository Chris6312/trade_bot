from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.models.core import AccountSnapshot
from backend.app.schemas.core import AccountSnapshotCreate, AccountSnapshotRead

router = APIRouter(prefix="/account-snapshots", tags=["account-snapshots"])


@router.post("", response_model=AccountSnapshotRead, status_code=201)
def create_account_snapshot(
    payload: AccountSnapshotCreate,
    db: Session = Depends(get_db),
) -> AccountSnapshotRead:
    record = AccountSnapshot(**payload.model_dump(exclude_none=True))
    db.add(record)
    db.commit()
    db.refresh(record)
    return AccountSnapshotRead.model_validate(record)


@router.get("/latest/{account_scope}", response_model=AccountSnapshotRead)
def get_latest_account_snapshot(account_scope: str, db: Session = Depends(get_db)) -> AccountSnapshotRead:
    record = (
        db.query(AccountSnapshot)
        .filter(AccountSnapshot.account_scope == account_scope)
        .order_by(AccountSnapshot.as_of.desc(), AccountSnapshot.id.desc())
        .first()
    )

    if record is None:
        raise HTTPException(status_code=404, detail="Account snapshot not found")

    return AccountSnapshotRead.model_validate(record)
