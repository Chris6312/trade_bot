from fastapi import APIRouter

from backend.app.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health", summary="Application health check")
def health_check() -> dict[str, object]:
    settings = get_settings()
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.app_env,
        "api_prefix": settings.api_v1_prefix,
        "backend_port": settings.backend_port,
    }
