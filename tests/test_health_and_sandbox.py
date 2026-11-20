"""
Tests for health check endpoint and environment configuration.
"""

import os
import sys
from fastapi.testclient import TestClient

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from ide_server import app


def test_health_check_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "aegis-web-ide"


def test_docker_compose_security_attributes():
    compose_path = os.path.join(root_dir, "docker-compose.yml")
    assert os.path.exists(compose_path)
    with open(compose_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Obsolete version key removed
    assert not content.strip().startswith("version:")
    assert "read_only: true" in content
    assert "cap_drop:" in content and "ALL" in content
    assert "no-new-privileges:true" in content
    assert "projects_data:" in content
