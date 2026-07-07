from fastapi import APIRouter

from app.interfaces.api.v1.auth import router as auth_router
from app.interfaces.api.v1.health import router as health_router
from app.interfaces.api.v1.workspace import router as workspace_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, prefix="/auth")
api_router.include_router(workspace_router, prefix="/workspaces")
