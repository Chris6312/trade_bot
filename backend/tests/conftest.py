from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import get_settings
from backend.app.db.base import Base
from backend.app.db.session import get_engine, reset_session_factory
from backend.app.models import core as core_models  # noqa: F401


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    db_path = tmp_path / "phase2_test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.delenv("DATABASE_URL_ALEMBIC", raising=False)

    get_settings.cache_clear()
    reset_session_factory()

    Base.metadata.create_all(bind=get_engine())

    from backend.app.main import app

    with TestClient(app) as test_client:
        yield test_client

    reset_session_factory()
    get_settings.cache_clear()
