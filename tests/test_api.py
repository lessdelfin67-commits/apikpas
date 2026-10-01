from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

HEADERS = {"X-API-Key": "9e8ZyWghoMoWUtt0oK1crfqBbGpspArVJ217pOr98vs"}


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_analyze_requires_exactly_one_source(client):
    response = client.post("/analyze", headers=HEADERS)
    assert response.status_code == 422


def test_rejects_local_path(client):
    response = client.post("/analyze", headers=HEADERS, data={"source": "file:///etc/passwd"})
    assert response.status_code == 422


def test_rejects_missing_api_key(client):
    response = client.post("/analyze")
    assert response.status_code == 401


def test_openapi_documents_endpoints(client):
    schema = client.get("/openapi.json").json()
    assert "/analyze" in schema["paths"]
    assert "/convert" in schema["paths"]
    assert "/jobs/{job_id}" in schema["paths"]
    assert "/download/{job_id}" in schema["paths"]
    assert "APIKeyHeader" in schema["components"]["securitySchemes"]
