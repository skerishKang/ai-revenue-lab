from pathlib import Path

WORKFLOW = Path(".github/workflows/b62-google-auth-production-activation-gate.yml").read_text(encoding="utf-8")


def test_activation_is_separate_and_explicitly_confirmed():
    assert "name: B62 Google Auth Production Activation Gate" in WORKFLOW
    assert "activate_production" in WORKFLOW
    assert 'CONFIRM_ACTIVATE_B62_GOOGLE_AUTH_PRODUCTION' in WORKFLOW
    assert "PREMUTATION_EXACT_MAIN_SHA=PASS" in WORKFLOW


def test_activation_sources_are_protected_github_secrets():
    assert "secrets.PADIEM_CHAT_GOOGLE_CLIENT_ID" in WORKFLOW
    assert "secrets.PADIEM_CHAT_GOOGLE_CLIENT_SECRET" in WORKFLOW
    assert "secrets.PADIEM_CHAT_SESSION_SECRET" in WORKFLOW
    assert "GOOGLE_CLIENT_ID_QUALITY=PASS" in WORKFLOW
    assert "GOOGLE_CLIENT_SECRET_QUALITY=PASS" in WORKFLOW
    assert "SESSION_SECRET_QUALITY=PASS" in WORKFLOW
    assert "AUTH_INPUT_VALUES_OUTPUT=0" in WORKFLOW


def test_first_activation_refuses_existing_auth_owned_bindings():
    for name in (
        "PADIEM_CHAT_AUTH_MODE",
        "PADIEM_CHAT_GOOGLE_CLIENT_ID",
        "PADIEM_CHAT_GOOGLE_CLIENT_SECRET",
        "PADIEM_CHAT_SESSION_SECRET",
    ):
        assert name in WORKFLOW
    assert "AUTH_FIRST_ACTIVATION_PRESTATE=PASS" in WORKFLOW


def test_secrets_use_workers_secret_api_and_are_never_echoed():
    assert "/workers/scripts/${B62_WORKER}/secrets" in WORKFLOW
    assert "GOOGLE_CLIENT_SECRET_PUT=PASS" in WORKFLOW
    assert "SESSION_SECRET_PUT=PASS" in WORKFLOW
    assert "SECRET_VALUES_READBACK=0" in WORKFLOW
    assert "SECRET_VALUES_OUTPUT=0" in WORKFLOW
    assert "set -x" not in WORKFLOW


def test_plain_text_activation_preserves_unrelated_bindings():
    assert '"type": "inherit", "version_id": "latest"' in WORKFLOW
    assert '"PADIEM_CHAT_AUTH_MODE", "type": "plain_text", "text": "google"' in WORKFLOW
    assert '"PADIEM_CHAT_GOOGLE_CLIENT_ID", "type": "plain_text"' in WORKFLOW
    assert "AUTH_SETTINGS_PATCH=PASS" in WORKFLOW
    assert "UNRELATED_BINDING_MUTATION=0" in WORKFLOW


def test_existing_google_auth_readback_contract_is_reused():
    assert "b62_google_auth_activation.py prereq" in WORKFLOW
    assert "b62_google_auth_activation.py verify" in WORKFLOW
    assert "AUTH_BINDING_READBACK=PASS" in WORKFLOW
    assert "/api/auth/status" in WORKFLOW
    assert "AUTH_STATUS_READY=PASS" in WORKFLOW


def test_rollback_is_bounded_to_first_activation_and_exact_readback():
    assert "B62_GOOGLE_AUTH_ROLLBACK=STARTED" in WORKFLOW
    assert "/secrets/PADIEM_CHAT_GOOGLE_CLIENT_SECRET" in WORKFLOW
    assert "/secrets/PADIEM_CHAT_SESSION_SECRET" in WORKFLOW
    assert "b62_binding_state_guard.py" in WORKFLOW
    assert "B62_GOOGLE_AUTH_ROLLBACK_READBACK=EXACT" in WORKFLOW
    assert "B62_GOOGLE_AUTH_ROLLBACK_READBACK=NOT_EXACT" in WORKFLOW


def test_gate_does_not_deploy_code_or_attempt_login_phase_b():
    assert "wrangler deploy" not in WORKFLOW
    assert "pywrangler deploy" not in WORKFLOW
    assert "LOGIN_ATTEMPT=0" in WORKFLOW
    assert "PHASE_B_REQUEST=0" in WORKFLOW
    assert "B62_GOOGLE_AUTH_PRODUCTION_ACTIVATION=PASS" in WORKFLOW
