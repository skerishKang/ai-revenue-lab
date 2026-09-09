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
        'test "$(git rev-parse HEAD)" = "${{ inputs.target_sha }}"',
        'test "$(git rev-parse origin/main)" = "${{ inputs.target_sha }}"',
        'test "${{ inputs.confirmation }}" = "RUN_B62_CLAW_PHASE_A_REAL_MODEL_CANARY"',
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


def test_claw_phase_a_smoke_gate_push_admission_does_not_fail_closed_on_ordinary_push() -> None:
    """#2267: ordinary pushes must not create a failing zero-job check.

    The workflow declares an explicit push trigger scoped to its own file so
    pushes touching the gate run source-contract (success), while ordinary
    pushes that do not touch the file create no run at all. The real canary
    job stays workflow_dispatch-only.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "  push:" in text
    assert '      - ".github/workflows/b62-claw-production-smoke-gate.yml"' in text
    assert "if: ${{ github.event_name == 'workflow_dispatch' }}" in text


def test_claw_phase_a_smoke_gate_event_context_safe_for_all_triggers() -> None:
    """#2267 second pass: every declared trigger must materialize >= 1 job.

    - source-contract admits push, pull_request, and workflow_dispatch.
    - each event uses a context-safe checkout (no dispatch-only inputs on
      push/PR paths, no PR-only fields on push/dispatch paths).
    - dispatch-only inputs.* never appear in top-level/global env.
    - the real canary job stays workflow_dispatch-only.
    """
    text = WORKFLOW.read_text(encoding="utf-8")

    assert (
        "if: ${{ github.event_name == 'pull_request' "
        "|| github.event_name == 'push' "
        "|| github.event_name == 'workflow_dispatch' }}" in text
    )
    assert "ref: ${{ github.event.pull_request.head.sha }}" in text
    assert "ref: ${{ github.sha }}" in text
    assert "ref: ${{ inputs.target_sha }}" in text

    top_level = text.split("jobs:")[0]
    top_env = top_level.split("env:")[1] if "env:" in top_level else ""
    assert "inputs." not in top_env

    canary_block = text.split("phase-a-production-canary:")[1]
    assert "if: ${{ github.event_name == 'workflow_dispatch' }}" in canary_block


def test_claw_phase_a_smoke_gate_has_no_unclosed_expression_sequences() -> None:
    """#2267 third pass: GitHub rejects the whole file before job materialization
    whenever any line contains an unclosed expression-open sequence. The Actions
    expression scanner runs over raw run-block text, so a literal built via
    string concatenation still fails admission; local YAML parsing cannot
    catch this, hence this scanner-style guard mirroring the server check.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    open_token = "$" + "{{"
    for line_no, line in enumerate(text.splitlines(), start=1):
        idx = 0
        while True:
            idx = line.find(open_token, idx)
            if idx < 0:
                break
            assert "}}" in line[idx + len(open_token) :], (
                f"unclosed expression sequence at line {line_no}"
            )
            idx += len(open_token)
