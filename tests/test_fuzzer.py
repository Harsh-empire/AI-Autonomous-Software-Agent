"""
Unit tests for Hacker Suite generator and heuristic fuzzer probes.
"""

import os
import sys
import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from agent.hacker_suite_generator import scan_flask_endpoints, ADVERSARIAL_PAYLOADS


def test_adversarial_payload_categories():
    expected_categories = [
        "sql_injection",
        "xss_script_injection",
        "ssti_template_injection",
        "command_injection",
        "path_traversal",
        "fuzzing_boundary"
    ]
    for category in expected_categories:
        assert category in ADVERSARIAL_PAYLOADS
        assert len(ADVERSARIAL_PAYLOADS[category]) > 0


def test_scan_flask_endpoints_on_sample_app():
    sample_proj = os.path.join(root_dir, "examples", "simple_task_management_app")
    scan_results = scan_flask_endpoints(sample_proj)
    
    assert "endpoints" in scan_results
    assert "forms" in scan_results
    
    routes = [ep["route"] for ep in scan_results["endpoints"]]
    assert "/" in routes or "/login" in routes
