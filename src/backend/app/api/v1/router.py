from fastapi import APIRouter, status

from app.api.v1.endpoints import games
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(games.router)


@api_router.get("/healthz", status_code=status.HTTP_200_OK)
def health_check() -> dict[str, str]:
    return {"service": settings.app_name, "status": "ok"}
