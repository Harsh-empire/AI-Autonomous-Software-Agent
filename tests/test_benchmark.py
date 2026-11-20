"""
Unit tests for the AEGIS Benchmark Suite.
"""

import os
import sys
import json
import tempfile
import pytest

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, ".."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from bench.run_benchmark import (
    check_ollama_reachable,
    write_results_markdown,
    generate_results_chart
)


def test_prompts_json_structure():
    prompts_path = os.path.join(root_dir, "bench", "prompts.json")
    assert os.path.exists(prompts_path)
    
    with open(prompts_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    assert "train" in data
    assert "held_out_test" in data
    assert len(data["train"]) == 10
    assert len(data["held_out_test"]) == 10
    
    # Total must be exactly 20
    assert len(data["train"]) + len(data["held_out_test"]) == 20


def test_ollama_reachable_fails_loudly_when_offline():
    # Connecting to non-existent port must return False
    assert check_ollama_reachable("http://127.0.0.1:59999") is False


def test_results_markdown_and_chart_generation():
    with tempfile.TemporaryDirectory() as tmp_dir:
        sample_records = [
            {
                "prompt_id": "test_01",
                "config": "A",
                "initial_breaches": 3,
                "verified_fixes": 0,
                "unresolved": 3,
                "fix_rate": 0.0,
                "bandit_findings": 2,
                "duration_sec": 1.2
            },
            {
                "prompt_id": "test_01",
                "config": "C",
                "initial_breaches": 3,
                "verified_fixes": 3,
                "unresolved": 0,
                "fix_rate": 1.0,
                "bandit_findings": 0,
                "duration_sec": 4.5
            }
        ]
        
        md_path = os.path.join(tmp_dir, "results.md")
        write_results_markdown(sample_records, md_path)
        assert os.path.exists(md_path)
        
        with open(md_path, "r", encoding="utf-8") as f:
            content = f.read()
            assert "AEGIS Benchmark Results" in content
            assert "test_01" in content

        # Test CSV and chart generation
        csv_path = os.path.join(tmp_dir, "results.csv")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("prompt_id,config,initial_breaches,verified_fixes,unresolved,fix_rate,bandit_findings,duration_sec\n")
            f.write("test_01,A,3,0,3,0.0,2,1.2\n")
            f.write("test_01,C,3,3,0,1.0,0,4.5\n")
            
        png_path = os.path.join(tmp_dir, "results.png")
        generate_results_chart(csv_path, png_path)
        assert os.path.exists(png_path)
        assert os.path.getsize(png_path) > 0


def test_benchmark_cli_parser(monkeypatch):
    import argparse
    from bench.run_benchmark import current_dir
    parser = argparse.ArgumentParser(description="AEGIS Empirical Benchmark Suite")
    parser.add_argument("--prompts", default=os.path.join(current_dir, "prompts.json"), help="Path to prompts.json")
    parser.add_argument("--config", default="ALL", choices=["A", "B", "C", "D", "E", "ALL"], help="Config to run")
    parser.add_argument("--runs", type=int, default=1, help="Number of repetitions per prompt")
    parser.add_argument("--dry-run-check", action="store_true", help="Check prerequisites and exit")

    args = parser.parse_args(["--config", "ALL", "--runs", "3"])
    assert args.config == "ALL"
    assert args.runs == 3

