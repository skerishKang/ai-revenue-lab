from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "b62-claw-production-smoke-gate.yml"


def test_claw_phase_a_production_smoke_gate_is_exact_main_bounded_and_secret_free() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    required = (
        "RUN_B62_CLAW_PHASE_A_REAL_MODEL_CANARY",
        "/api/claw/manual-intake/execute",
        '"action":"summary"',
        "PHASE_A_EXACT_MAIN=PASS",
        "MODEL_RESULT_NONEMPTY=PASS",
        "P01_RUN_ID_PRESENT=PASS",
        "NO_EXTERNAL_SIDE_EFFECT_ACTION=PASS",
        "SECRET_VALUES_OUTPUT=0",
        "PRODUCTION_MUTATION=0",
        "environment: production",
        "git fetch --no-tags --depth=1 origin main",
        'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"',
        "--max-time 45",
    )
    for needle in required:
        assert needle in text

    assert "${{ secrets." not in text
    assert "-H 'Cookie:" not in text
    assert "-H 'Authorization:" not in text
    assert "PADIEM_CHAT_SESSION_SECRET" not in text
    assert "GOOGLE_ACCESS_TOKEN" not in text


def test_claw_phase_a_canary_uses_synthetic_non_artifact_action_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'payload=\'{"channel":"other","action":"summary"' in text
    assert '"action":"quote"' not in text
    assert '"action":"order"' not in text
    assert "human session material stored in CI: no" in text
    assert "external send/write: no" in text
