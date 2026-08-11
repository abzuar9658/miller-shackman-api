from fastapi import APIRouter, Response, status
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.metrics import outbound_send_dispatch_metrics


class HealthResponse(BaseModel):
    status: str
    service: str


router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(status="ok", service="miller-schackman-api")


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    if not get_settings().metrics_enabled:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    return Response(
        content=generate_latest(outbound_send_dispatch_metrics.registry),
        media_type=CONTENT_TYPE_LATEST,
    )
