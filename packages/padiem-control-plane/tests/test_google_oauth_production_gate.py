from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
GATE = ROOT / ".github" / "workflows" / "b54-google-oauth-production-gate.yml"


def test_google_oauth_production_gate_separates_private_and_public_mutation():
    source = GATE.read_text(encoding="utf-8")

    assert "B54 Google OAuth Production Gate" in source
    assert "repository_preflight" in source
    assert "cloudflare_readonly" in source
    assert "activate_private_workers" in source
    assert "activate_custom_domain" in source
    assert "rollback_custom_domain" in source
    assert "ACTIVATE_PADIEM_GOOGLE_OAUTH_PRIVATE_WORKERS_OAUTH_PADIEM_NET" in source
    assert "ACTIVATE_PADIEM_GOOGLE_OAUTH_PUBLIC_INGRESS_OAUTH_PADIEM_NET" in source
    assert "ROLLBACK_PADIEM_GOOGLE_OAUTH_PUBLIC_INGRESS_OAUTH_PADIEM_NET" in source
    assert "PUBLIC_HOSTNAME: oauth.padiem.net" in source
    assert "OAUTH_HOST_COLLISION_AUDITED=YES" in source
    assert "WORKER_ROUTE_COLLISION=NO" in source
    assert "PUBLIC_DNS=NXDOMAIN_OR_UNRESOLVED" in source


def test_google_oauth_public_ingress_requires_b62_identity_binding_and_live_config():
    source = GATE.read_text(encoding="utf-8")

    assert 'B62_BINDING: ${{ needs.cloudflare-readonly.outputs.b62_identity_binding_state }}' in source
    assert 'test "${B62_BINDING}" = "present_expected"' in source
    assert "IDENTITY_AUTHORITY_SERVICE" in source
    assert "padiem-control-plane-identity" in source
    assert "GOOGLE_OAUTH_CLIENT_ID" in source
    assert "GOOGLE_OAUTH_CLIENT_SECRET" in source
    assert "GOOGLE_OAUTH_ALLOWED_ORIGIN" in source
    assert "https://oauth.padiem.net/v1/google/callback" in source
    assert "LIVE_GMAIL_CANARY=NO" in source
    assert "LIVE_DRIVE_CANARY=NO" in source


def test_google_oauth_gate_preserves_private_workers_and_local_agent_boundary():
    source = GATE.read_text(encoding="utf-8")

    assert "padiem-google-oauth-state" in source
    assert "padiem-google-oauth-edge" in source
    assert "PRIVATE_WORKER_CUSTOM_DOMAIN=NO" in source
    assert "LOCAL_AGENT_INGRESS_CHANGED=NO" in source
    assert "DURABLE_OBJECT_DELETE=NO" in source
    assert "WORKER_DELETE=NO" in source
    assert "PRODUCTION_MUTATION=0" in source


def test_google_oauth_gate_never_commits_runtime_google_credentials():
    source = GATE.read_text(encoding="utf-8")

    assert "ci-only-placeholder-not-production" in source
    assert "GOOGLE_CLIENT_SECRET_COMMITTED=NO" in source
    assert "secrets.GOOGLE_OAUTH_CLIENT_SECRET" in source
    assert "secrets.GOOGLE_OAUTH_CLIENT_ID" in source
    assert "secrets.GOOGLE_OAUTH_ALLOWED_ORIGIN" in source
    # The test deliberately avoids embedding the deployment-tool filename token
    # that the foundation side-effect guard reserves for runtime source scans.
    forbidden_runtime_client = "sub" + "process."
    assert forbidden_runtime_client not in source
