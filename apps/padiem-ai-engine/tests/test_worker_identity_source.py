from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]


def test_worker_enforces_identity_on_execute_and_stream():
    source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    assert "_authenticate_non_health_request" in source
    assert "authenticate_request" in source
    assert 'if path != HEALTH_PATH:' in source
    assert 'CALLER_ID_HEADER = "x-padiem-engine-caller"' in (
        APP_ROOT / "app" / "identity_enforcement.py"
    ).read_text(encoding="utf-8")
    assert 'CALLER_CREDENTIAL_HEADER = "x-padiem-engine-credential"' in (
        APP_ROOT / "app" / "identity_enforcement.py"
    ).read_text(encoding="utf-8")


def test_worker_does_not_make_health_require_caller_credential():
    source = (APP_ROOT / "worker.py").read_text(encoding="utf-8")
    assert "if path != HEALTH_PATH:" in source
    assert "service_identity" in source
