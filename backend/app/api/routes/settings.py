from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.deps import get_db
from backend.app.core.config import get_settings
from backend.app.models.core import Setting
from backend.app.schemas.core import RuntimeSettingsSnapshot, SettingBatchUpsertRequest, SettingRead, SettingUpsert
from backend.app.services.settings_service import build_runtime_snapshot, get_setting, upsert_setting

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=list[SettingRead])
def list_settings(prefix: str | None = None, db: Session = Depends(get_db)) -> list[SettingRead]:
    query = db.query(Setting)
    if prefix:
        query = query.filter(Setting.key.startswith(prefix))
    rows = query.order_by(Setting.key.asc()).all()
    return [SettingRead.model_validate(row) for row in rows]


@router.get("/runtime/snapshot", response_model=RuntimeSettingsSnapshot)
def get_runtime_snapshot(db: Session = Depends(get_db)) -> RuntimeSettingsSnapshot:
    settings = get_settings()
    snapshot = build_runtime_snapshot(db, settings)
    return RuntimeSettingsSnapshot(**snapshot)


@router.post("/batch", response_model=list[SettingRead])
def put_settings_batch(payload: SettingBatchUpsertRequest, db: Session = Depends(get_db)) -> list[SettingRead]:
    rows: list[SettingRead] = []
    for item in payload.items:
        record = upsert_setting(
            db,
            key=item.key,
            value=item.value,
            value_type=item.value_type,
            description=item.description,
            is_secret=item.is_secret,
        )
        rows.append(SettingRead.model_validate(record))
    return rows


@router.get("/{key}", response_model=SettingRead)
def get_setting_by_key(key: str, db: Session = Depends(get_db)) -> SettingRead:
    record = get_setting(db, key)

    if record is None:
        raise HTTPException(status_code=404, detail="Setting not found")

    return SettingRead.model_validate(record)


@router.put("/{key}", response_model=SettingRead)
def put_setting(key: str, payload: SettingUpsert, db: Session = Depends(get_db)) -> SettingRead:
    record = upsert_setting(
        db,
        key=key,
        value=payload.value,
        value_type=payload.value_type,
        description=payload.description,
        is_secret=payload.is_secret,
    )
    return SettingRead.model_validate(record)
