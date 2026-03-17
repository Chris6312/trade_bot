from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes.account_snapshots import router as account_snapshot_router
from backend.app.api.routes.ci_crypto_regime import router as ci_crypto_regime_router
from backend.app.api.routes.controls import router as controls_router
from backend.app.api.routes.data import router as data_router
from backend.app.api.routes.execution import router as execution_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.operations import router as operations_router
from backend.app.api.routes.positions import router as position_router
from backend.app.api.routes.regime import router as regime_router
from backend.app.api.routes.risk import router as risk_router
from backend.app.api.routes.settings import router as settings_router
from backend.app.api.routes.universe import router as universe_router
from backend.app.api.routes.stops import router as stop_router
from backend.app.api.routes.strategy import router as strategy_router
from backend.app.api.routes.system_events import router as system_event_router
from backend.app.api.routes.workflows import router as workflow_router
from backend.app.core.config import get_settings
from backend.app.db.session import get_session_factory
from backend.app.workers.scheduler_worker import SchedulerWorker

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    scheduler = SchedulerWorker(session_factory=get_session_factory(), settings=settings)
    app.state.scheduler = scheduler
    scheduler.start()
    try:
        yield
    finally:
        scheduler.stop()


app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(settings_router, prefix=settings.api_v1_prefix)
app.include_router(controls_router, prefix=settings.api_v1_prefix)
app.include_router(data_router, prefix=settings.api_v1_prefix)
app.include_router(universe_router, prefix=settings.api_v1_prefix)
app.include_router(workflow_router, prefix=settings.api_v1_prefix)
app.include_router(account_snapshot_router, prefix=settings.api_v1_prefix)
app.include_router(ci_crypto_regime_router, prefix=settings.api_v1_prefix)
app.include_router(system_event_router, prefix=settings.api_v1_prefix)
app.include_router(regime_router, prefix=settings.api_v1_prefix)
app.include_router(strategy_router, prefix=settings.api_v1_prefix)
app.include_router(risk_router, prefix=settings.api_v1_prefix)
app.include_router(execution_router, prefix=settings.api_v1_prefix)
app.include_router(stop_router, prefix=settings.api_v1_prefix)
app.include_router(position_router, prefix=settings.api_v1_prefix)
app.include_router(operations_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {
        "message": f"{settings.app_name} backend is running.",
        "health": "/health",
    }
