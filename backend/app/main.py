from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.routes.account_snapshots import router as account_snapshot_router
from backend.app.api.routes.health import router as health_router
from backend.app.api.routes.regime import router as regime_router
from backend.app.api.routes.settings import router as settings_router
from backend.app.api.routes.system_events import router as system_event_router
from backend.app.api.routes.workflows import router as workflow_router
from backend.app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.settings = settings
    yield


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
app.include_router(workflow_router, prefix=settings.api_v1_prefix)
app.include_router(account_snapshot_router, prefix=settings.api_v1_prefix)
app.include_router(system_event_router, prefix=settings.api_v1_prefix)
app.include_router(regime_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["meta"])
def root() -> dict[str, str]:
    return {
        "message": f"{settings.app_name} backend is running.",
        "health": "/health",
    }
