import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.interfaces.api.v1 import health
from app.main import create_app


def test_health_check() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "miller-schackman-api"}


def test_metrics_endpoint_exposes_prometheus_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health, "get_settings", lambda: Settings(metrics_enabled=True))
    client = TestClient(create_app())

    response = client.get("/api/v1/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "miller_schackman_outbound_send_dispatch_cycles" in response.text


def test_metrics_endpoint_is_disabled_by_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(health, "get_settings", lambda: Settings(metrics_enabled=False))
    client = TestClient(create_app())

    response = client.get("/api/v1/metrics")

    assert response.status_code == 404
