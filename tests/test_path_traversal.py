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

from ide_server import app, safe_join


def test_safe_join_valid_paths():
    base = os.path.realpath(root_dir)
    
    # Valid file in base
    res = safe_join(base, "ide_server.py")
    assert res == os.path.realpath(os.path.join(base, "ide_server.py"))
    
    # Valid subdirectory file
    res = safe_join(base, "agent", "main.py")
    assert res == os.path.realpath(os.path.join(base, "agent", "main.py"))


def test_safe_join_rejects_parent_traversal():
    base = os.path.realpath(root_dir)
    
    traversal_payloads = [
        "..",
        "../",
        "..\\",
        "../../../../etc/passwd",
        "..\\..\\..\\windows\\win.ini",
        "subdir/../../parent_leak"
    ]
    
    for payload in traversal_payloads:
        with pytest.raises(HTTPException) as exc_info:
            safe_join(base, payload)
        assert exc_info.value.status_code == 400
        assert "Invalid path" in exc_info.value.detail


def test_safe_join_rejects_absolute_path_escape():
    base = os.path.realpath(root_dir)
    
    escape_payloads = [
        "/etc/passwd",
        "/var/log/syslog",
        "C:\\Windows\\System32\\cmd.exe",
        "D:\\sensitive_data"
    ]
    
    for payload in escape_payloads:
        with pytest.raises(HTTPException) as exc_info:
            safe_join(base, payload)
        assert exc_info.value.status_code == 400


def test_api_file_content_path_traversal():
    client = TestClient(app)
    
    # Attempting to read outside workspace
    response = client.get("/api/file-content?project=simple_task_management_app&file=../../../../etc/passwd")
    assert response.status_code == 400
    assert "Invalid path" in response.json()["detail"]


def test_api_export_zip_path_traversal():
    client = TestClient(app)
    
    response = client.get("/api/export-zip?project=..")
    assert response.status_code == 400
    assert "Invalid path" in response.json()["detail"]


def test_api_security_audit_nonexistent_and_traversal():
    client = TestClient(app)
    
    # Traversal attempt
    response = client.get("/api/security-audit?project=..")
    assert response.status_code == 400
    
    # Nonexistent project
    response = client.get("/api/security-audit?project=definitely_nonexistent_project_xyz")
    assert response.status_code == 404
