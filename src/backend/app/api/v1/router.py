from fastapi import APIRouter, Depends, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.v1.endpoints import games
from app.core.config import settings
from app.db.session import get_db

api_router = APIRouter()
api_router.include_router(games.router)


@api_router.get("/healthz", status_code=status.HTTP_200_OK)
def health_check() -> dict[str, str]:
    return {"service": settings.app_name, "status": "ok"}


@api_router.get("/health/db")
def health_check_db(session: Session = Depends(get_db)):
    try:
        session.execute(text("SELECT 1"))
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return {"status": "error", "db": "disconnected", "detail": str(e)}
