from fastapi import APIRouter

from app.interfaces.api.v1.attention import router as attention_router
from app.interfaces.api.v1.auth import router as auth_router
from app.interfaces.api.v1.campaigns import router as campaigns_router
from app.interfaces.api.v1.crm_agent_mappings import router as crm_agent_mappings_router
from app.interfaces.api.v1.handoffs import router as handoffs_router
from app.interfaces.api.v1.health import router as health_router
from app.interfaces.api.v1.leads import router as leads_router
from app.interfaces.api.v1.listing_sources import router as listing_sources_router
from app.interfaces.api.v1.paused_search_tracks import (
    router as paused_search_tracks_router,
)
from app.interfaces.api.v1.preflight import router as preflight_router
from app.interfaces.api.v1.reporting import router as reporting_router
from app.interfaces.api.v1.webhooks import router as webhook_router
from app.interfaces.api.v1.workspace import router as workspace_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["health"])
api_router.include_router(auth_router, prefix="/auth")
api_router.include_router(webhook_router, prefix="/webhooks")
api_router.include_router(workspace_router, prefix="/workspaces")
api_router.include_router(crm_agent_mappings_router, prefix="/workspaces")
api_router.include_router(campaigns_router, prefix="/workspaces")
api_router.include_router(attention_router, prefix="/workspaces")
api_router.include_router(handoffs_router, prefix="/workspaces")
api_router.include_router(leads_router, prefix="/workspaces")
api_router.include_router(listing_sources_router, prefix="/workspaces")
api_router.include_router(paused_search_tracks_router, prefix="/workspaces")
api_router.include_router(preflight_router, prefix="/workspaces")
api_router.include_router(reporting_router, prefix="/workspaces")
