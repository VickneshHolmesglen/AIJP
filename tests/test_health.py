import pytest
from fastapi.testclient import TestClient

from app.main import app


def test_liveness_needs_no_database():
    # Not used as a context manager, so the lifespan (DB init) does not run.
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.integration
def test_readiness_reports_pgvector(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
