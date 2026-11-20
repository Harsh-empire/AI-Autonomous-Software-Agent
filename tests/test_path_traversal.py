"""
Regression tests for Path Traversal vulnerabilities and safe_join protection.
"""

import os
import sys
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

# Ensure root directory is on path
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from ide_server import app, safe_join, resolve_project_dir


def test_safe_join_valid_paths():
    base = os.path.realpath(root_dir)
    res = safe_join(base, "ide_server.py")
    assert res == os.path.realpath(os.path.join(base, "ide_server.py"))
    
    res = safe_join(base, "agent", "main.py")
    assert res == os.path.realpath(os.path.join(base, "agent", "main.py"))


@pytest.mark.parametrize("payload", [
    "..",
    "../",
    "../../../../etc/passwd",
    "subdir/../../parent_leak",
    pytest.param("..\\", marks=pytest.mark.skipif(os.name != "nt", reason="Windows-style path")),
    pytest.param("..\\..\\..\\windows\\win.ini", marks=pytest.mark.skipif(os.name != "nt", reason="Windows-style path")),
])
def test_safe_join_rejects_parent_traversal(payload):
    base = os.path.realpath(root_dir)
    with pytest.raises(HTTPException) as exc_info:
        safe_join(base, payload)
    assert exc_info.value.status_code == 400
    assert "Invalid path" in exc_info.value.detail


@pytest.mark.parametrize("payload", [
    "/etc/passwd",
    "/var/log/syslog",
    pytest.param("C:\\Windows\\System32\\cmd.exe", marks=pytest.mark.skipif(os.name != "nt", reason="Windows-style drive path")),
    pytest.param("D:\\sensitive_data", marks=pytest.mark.skipif(os.name != "nt", reason="Windows-style drive path")),
])
def test_safe_join_rejects_absolute_path_escape(payload):
    base = os.path.realpath(root_dir)
    with pytest.raises(HTTPException) as exc_info:
        safe_join(base, payload)
    assert exc_info.value.status_code == 400


def test_resolve_project_dir_rejects_traversal_and_invalid():
    with pytest.raises(HTTPException) as exc:
        resolve_project_dir("..")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        resolve_project_dir("../../etc/passwd")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        resolve_project_dir("nonexistent_random_proj_99")
    assert exc.value.status_code == 400


def test_api_file_content_path_traversal():
    client = TestClient(app)
    
    # Attempting to read outside workspace via file parameter
    response = client.get("/api/file-content?project=simple_task_management_app&file=../../../../etc/passwd")
    assert response.status_code == 400
    assert "Invalid path" in response.json()["detail"]

    # Attempting to escape via project parameter
    response = client.get("/api/file-content?project=..&file=app.py")
    assert response.status_code == 400


def test_api_export_zip_path_traversal():
    client = TestClient(app)
    response = client.get("/api/export-zip?project=..")
    assert response.status_code == 400


def test_api_project_files_path_traversal():
    client = TestClient(app)
    response = client.get("/api/project-files?project=..")
    assert response.status_code == 400


def test_api_security_audit_nonexistent_and_traversal():
    client = TestClient(app)
    
    # Traversal attempt
    response = client.get("/api/security-audit?project=..")
    assert response.status_code == 400
    
    # Nonexistent project
    response = client.get("/api/security-audit?project=definitely_nonexistent_project_xyz")
    assert response.status_code == 400

    # Project exists but has no audit file: returns 404 with status "no audit yet", never default score
    response = client.get("/api/security-audit?project=simple_task_management_web_app")
    assert response.status_code == 404
    data = response.json()
    assert data["status"] == "no audit yet"
    assert "final_shield_health_score" not in data
