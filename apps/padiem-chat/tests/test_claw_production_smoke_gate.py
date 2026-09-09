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

    secret_context = "${{" + " secrets."
    cookie_header = "-H " + "'Cookie:"
    auth_header = "-H " + "'Authorization:"
    session_secret_name = "PADIEM_CHAT_" + "SESSION_SECRET"
    google_access_token_name = "GOOGLE_" + "ACCESS_TOKEN"
    assert secret_context not in text
    assert cookie_header not in text
    assert auth_header not in text
    assert session_secret_name not in text
    assert google_access_token_name not in text


def test_claw_phase_a_canary_uses_synthetic_non_artifact_action_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'payload=\'{"channel":"other","action":"summary"' in text
    assert '"action":"quote"' not in text
    assert '"action":"order"' not in text
    assert "human session material stored in CI: no" in text
    assert "external send/write: no" in text
