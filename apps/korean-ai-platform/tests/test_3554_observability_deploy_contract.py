"""B14 #3554: owner-approved persistent safe Cloudflare logs: offline config contract."""
from pathlib import Path
import tomllib

WORKER_ROOT = Path(__file__).resolve().parents[1]


def test_b14_observability_enabled_with_full_sampling_and_no_new_secret():
    cfg = tomllib.loads((WORKER_ROOT / "wrangler.toml").read_text("utf-8"))
    assert cfg["name"] == "ai-revenue-korean-ai-platform"
    assert cfg["vars"]["B14_PROVIDER_MODE"] == "live"
    assert cfg["observability"] == {"enabled": True, "head_sampling_rate": 1}
    # Avoid accidentally changing the provider-secret registry when enabling logs.
    secrets = cfg["secrets_store_secrets"]
    assert len({row["binding"] for row in secrets}) == len(secrets)
    assert "PADIEM_KIRAAI_API_KEY" in {row["binding"] for row in secrets}
    assert all(set(row) == {"binding", "store_id", "secret_name"} for row in secrets)


def test_b14_phase_logs_do_not_format_any_sensitive_untrusted_fields():
    from app.pilot.provider_timeout_diagnostics import (
        classify_timeout_phase, log_provider_timeout, log_gateway_deadline
    )
    import httpx
    import logging
    import io
    handler = logging.StreamHandler(output := io.StringIO())
    logger = logging.getLogger("b14_3554_persist_log_safety")
    logger.addHandler(handler)
    try:
        logger.setLevel(logging.WARNING)
        log_provider_timeout(logger,"kira",httpx.ReadTimeout("PRIVATE_TOKEN_OR_PDF_BODY"),"completed")
        log_gateway_deadline(logger,"kira")
        assert "b14_safe_timeout provider=kira phase=read mode=completed" in output.getvalue()
        assert "b14_gateway_deadline provider=kira phase=overall" in output.getvalue()
        assert "PRIVATE_TOKEN_OR_PDF_BODY" not in output.getvalue()
        assert classify_timeout_phase(httpx.ReadTimeout("synthetic")) == "read"
    finally:
        logger.removeHandler(handler)
