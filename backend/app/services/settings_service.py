from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.orm import Session

from backend.app.core.config import Settings
from backend.app.models.core import Setting

T = TypeVar("T")


def get_setting(db: Session, key: str) -> Setting | None:
    return db.query(Setting).filter(Setting.key == key).one_or_none()


def upsert_setting(
    db: Session,
    *,
    key: str,
    value: str,
    value_type: str = "string",
    description: str | None = None,
    is_secret: bool = False,
) -> Setting:
    record = get_setting(db, key)

    if record is None:
        record = Setting(
            key=key,
            value=value,
            value_type=value_type,
            description=description,
            is_secret=is_secret,
        )
        db.add(record)
    else:
        record.value = value
        record.value_type = value_type
        record.description = description
        record.is_secret = is_secret

    db.flush()
    return record


def resolve_runtime_value(
    db: Session,
    *,
    key: str,
    default: T,
    caster: Callable[[str], T],
) -> tuple[T, str]:
    record = get_setting(db, key)

    if record is None:
        return default, "environment"

    try:
        return caster(record.value), "database"
    except (TypeError, ValueError):
        return default, "environment"




def resolve_str_setting(db: Session, key: str, *, default: str) -> str:
    record = get_setting(db, key=key)
    if record is None or record.value in {None, ""}:
        return str(default)
    return str(record.value)


def resolve_bool_setting(db: Session, key: str, *, default: bool) -> bool:
    record = get_setting(db, key=key)
    if record is None or record.value in {None, ""}:
        return bool(default)
    return str(record.value).strip().lower() in {"1", "true", "yes", "on"}


def resolve_int_setting(db: Session, key: str, *, default: int) -> int:
    record = get_setting(db, key=key)
    if record is None or record.value in {None, ""}:
        return int(default)
    try:
        return int(record.value)
    except (TypeError, ValueError):
        return int(default)


def resolve_float_setting(db: Session, key: str, *, default: float) -> float:
    record = get_setting(db, key=key)
    if record is None or record.value in {None, ""}:
        return float(default)
    try:
        return float(record.value)
    except (TypeError, ValueError):
        return float(default)

def build_runtime_snapshot(db: Session, env_settings: Settings) -> dict[str, object]:
    app_name, app_name_source = resolve_runtime_value(
        db,
        key="app_name",
        default=env_settings.app_name,
        caster=str,
    )
    app_env, app_env_source = resolve_runtime_value(
        db,
        key="app_env",
        default=env_settings.app_env,
        caster=str,
    )
    api_v1_prefix, api_v1_prefix_source = resolve_runtime_value(
        db,
        key="api_v1_prefix",
        default=env_settings.api_v1_prefix,
        caster=str,
    )
    backend_port, backend_port_source = resolve_runtime_value(
        db,
        key="backend_port",
        default=env_settings.backend_port,
        caster=int,
    )
    frontend_port, frontend_port_source = resolve_runtime_value(
        db,
        key="frontend_port",
        default=env_settings.frontend_port,
        caster=int,
    )
    postgres_host_port, postgres_host_port_source = resolve_runtime_value(
        db,
        key="postgres_host_port",
        default=env_settings.postgres_host_port,
        caster=int,
    )
    cors_origin_csv, cors_origin_source = resolve_runtime_value(
        db,
        key="cors_origins",
        default=env_settings.cors_origins,
        caster=str,
    )

    return {
        "app_name": app_name,
        "app_env": app_env,
        "api_v1_prefix": api_v1_prefix,
        "backend_port": backend_port,
        "frontend_port": frontend_port,
        "postgres_host_port": postgres_host_port,
        "cors_origins": [item.strip() for item in cors_origin_csv.split(",") if item.strip()],
        "database_url_masked": env_settings.masked_database_url,
        "setting_sources": {
            "app_name": app_name_source,
            "app_env": app_env_source,
            "api_v1_prefix": api_v1_prefix_source,
            "backend_port": backend_port_source,
            "frontend_port": frontend_port_source,
            "postgres_host_port": postgres_host_port_source,
            "cors_origins": cors_origin_source,
            "database_url_masked": "environment",
        },
    }
