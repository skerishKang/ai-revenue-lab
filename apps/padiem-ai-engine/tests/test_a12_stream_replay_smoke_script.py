"""Unit tests for A12 streaming idempotency replay smoke script & deploy gate (#2025)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch
import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]
SMOKE_PATH = APP_ROOT / "scripts" / "a12_stream_replay_production_smoke.py"

spec = importlib.util.spec_from_file_location("a12_stream_replay_production_smoke", SMOKE_PATH)
assert spec is not None and spec.loader is not None
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_require_env_skips_upstream_honestly(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(smoke, "CALLER_ID", ""), patch.object(smoke, "CALLER_SECRET", ""):
        assert smoke._require_env() is False
        _, err = capsys.readouterr()
        assert "A12_STREAM_REPLAY_SMOKE=SKIPPED_UPSTREAM" in err


def test_s0_health_detects_advertised_stream_endpoint() -> None:
    fake_health = {
        "status": "ok",
        "capabilities": {"provider_streaming_run": "available"},
        "endpoints": [{"path": "/internal/v1/stream", "method": "POST"}],
    }
    with patch.object(smoke, "_request_json", return_value=(200, fake_health)):
        assert smoke.s0_health() is True


def test_s0_health_fails_if_endpoint_missing() -> None:
    fake_health = {
        "status": "ok",
        "capabilities": {"provider_streaming_run": "available"},
        "endpoints": [],
    }
    with patch.object(smoke, "_request_json", return_value=(200, fake_health)), patch.object(smoke, "_failures", []):
        assert smoke.s0_health() is False


def test_s1_first_stream_run_extracts_answer_and_validates_terminal() -> None:
    event_lines = [
        {"ok": True, "event": {"delta_content": "안녕", "done": False}},
        {"ok": True, "event": {"delta_content": "하세요", "done": False}},
        {"ok": True, "event": {"delta_content": None, "answer": "안녕하세요", "done": True}},
    ]
    with patch.object(smoke, "_request_stream", return_value=(200, event_lines, "")):
        ok, answer = smoke.s1_first_stream_run(smoke._stream_payload())
        assert ok is True
        assert answer == "안녕하세요"


def test_s1_first_stream_run_fails_if_unexpectedly_replayed() -> None:
    event_lines = [
        {"ok": True, "replayed": True, "event": {"delta_content": None, "answer": "cached", "done": True}},
    ]
    with patch.object(smoke, "_request_stream", return_value=(200, event_lines, "")), patch.object(smoke, "_failures", []):
        ok, answer = smoke.s1_first_stream_run(smoke._stream_payload())
        assert ok is False
        assert answer is None


def test_s2_replay_stream_run_requires_exact_single_replayed_line() -> None:
    replay_lines = [
        {
            "ok": True,
            "replayed": True,
            "event": {
                "delta_content": None,
                "answer": "안녕하세요",
                "done": True,
            },
        }
    ]
    with patch.object(smoke, "_request_stream", return_value=(200, replay_lines, "")):
        assert smoke.s2_replay_stream_run(smoke._stream_payload(), "안녕하세요") is True


def test_s2_replay_stream_run_rejects_multi_line_or_unmarked_replay() -> None:
    multi_lines = [
        {"ok": True, "event": {"delta_content": "안녕", "done": False}},
        {"ok": True, "event": {"delta_content": None, "answer": "안녕", "done": True}},
    ]
    with patch.object(smoke, "_request_stream", return_value=(200, multi_lines, "")), patch.object(smoke, "_failures", []):
        assert smoke.s2_replay_stream_run(smoke._stream_payload(), "안녕") is False


def test_s3_conflict_blocks_before_execution() -> None:
    conflict_res = {
        "ok": False,
        "error": {"code": "idempotency_conflict", "message": "Key conflict."},
    }
    with patch.object(smoke, "_request_json", return_value=(409, conflict_res)):
        assert smoke.s3_conflict_blocks_before_execution(smoke._stream_payload()) is True


def test_b54_deploy_gate_workflow_contains_a12_smoke_step() -> None:
    workflow_path = REPO_ROOT / ".github" / "workflows" / "b54-engine-production-deploy-gate.yml"
    assert workflow_path.exists()
    content = workflow_path.read_text(encoding="utf-8")

    assert "a12_stream_replay_production_smoke.py" in content
    assert "A12_STREAM_REPLAY_SMOKE=PASS" in content