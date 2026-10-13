"""#4139 read-only readiness must prove isolated bindings, never assume them."""
from __future__ import annotations

import json
from pathlib import Path
import tomllib

from scripts import connector_cloudflare_runtime_readiness as readiness

CHAT = Path(__file__).resolve().parents[1]
ACCEPTANCE_CHAT = CHAT / "wrangler.connector-acceptance-4139.toml"
IDENTITY_ACCEPTANCE = (
    CHAT.parents[1] / "packages/padiem-control-plane"
    / "wrangler.identity-authority-acceptance-4139.jsonc"
)
BROKER_ACCEPTANCE = (
    CHAT.parents[1] / "packages/padiem-control-plane"
    / "wrangler.local-agent-broker-acceptance-4139.jsonc"
)


def _version_view(bindings: list[tuple[str, str]]) -> dict:
    return {"resources": {"bindings": [
        {"name": name, "type": kind} for name, kind in bindings
    ]}}


def _stub_wrangler(monkeypatch, view: dict) -> None:
    """Answer only the three read-only wrangler calls, never a mutation."""
    def fake(*, config, args, **_kwargs):
        if args[0] == "deployments":
            return [{"created_on": "2026-10-14T00:00:00Z", "versions": [
                {"version_id": "0000", "percentage": 100},
            ]}]
        if args[0] == "versions":
            return view
        return None

    monkeypatch.setattr(readiness.shutil, "which", lambda _name: "wrangler")
    monkeypatch.setattr(
        readiness, "_run_readonly",
        lambda **kwargs: fake(config=kwargs["config"], args=kwargs["args"]),
    )


def _facts(monkeypatch, bindings: list[tuple[str, str]]) -> dict:
    _stub_wrangler(monkeypatch, _version_view(bindings))
    return readiness.inventory()


def test_isolated_chat_bindings_are_proved_from_the_deployed_version(monkeypatch):
    report = _facts(monkeypatch, [
        ("IDENTITY_AUTHORITY_SERVICE", "service"),
        ("LOCAL_AGENT_BROKER_AUTHORITY_SERVICE", "service"),
        ("PADIEM_CHAT_DB", "d1"),
        ("PADIEM_CHAT_SESSION_SECRET", "secret_text"),
        ("PADIEM_CHAT_AUTH_MODE", "plain_text"),
    ])
    chat = report["workers"]["acceptance_chat"]
    assert chat["acceptance_private_services"] == {
        "IDENTITY_AUTHORITY_SERVICE": True,
        "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": True,
    }
    assert chat["acceptance_d1_bound"] is True
    assert chat["acceptance_session_secret_bound"] is True
    assert chat["acceptance_password_auth_setting_present"] is True
    assert "isolated_acceptance_runtime_bindings_not_ready" in report["blocking_facts"]

    # An unbound D1, a wrong-kind service and a missing secret all stay false;
    # the readiness gate must never assume a binding that is not deployed.
    partial = _facts(monkeypatch, [
        ("IDENTITY_AUTHORITY_SERVICE", "service"),
        ("LOCAL_AGENT_BROKER_AUTHORITY_SERVICE", "plain_text"),
        ("PADIEM_CHAT_AUTH_MODE", "plain_text"),
    ])
    chat = partial["workers"]["acceptance_chat"]
    assert chat["acceptance_private_services"] == {
        "IDENTITY_AUTHORITY_SERVICE": True,
        "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE": False,
    }
    assert chat["acceptance_d1_bound"] is False
    assert chat["acceptance_session_secret_bound"] is False
    assert chat["acceptance_password_auth_setting_present"] is True
    assert "isolated_acceptance_runtime_bindings_not_ready" in (
        partial["blocking_facts"]
    )

    # Password auth is an explicit binding, not a source-template assumption.
    unauthenticated = _facts(monkeypatch, [
        ("PADIEM_CHAT_DB", "d1"),
    ])
    assert unauthenticated["workers"]["acceptance_chat"][
        "acceptance_password_auth_setting_present"
    ] is False


def test_isolated_durable_state_and_secrets_are_proved_per_worker(monkeypatch):
    _stub_wrangler(monkeypatch, _version_view([
        ("CONTROL_PLANE_IDENTITY", "durable_object_namespace"),
        ("LOCAL_AGENT_BROKER_STATE", "durable_object_namespace"),
        ("CONTROL_PLANE_IDENTITY_LOOKUP_KEY", "secret_text"),
        ("GOOGLE_CONNECT_TICKET_KEY", "secret_text"),
        ("LOCAL_AGENT_BROKER_PEPPER", "secret_text"),
    ]))
    report = readiness.inventory()
    identity = report["workers"]["acceptance_identity"]
    broker = report["workers"]["acceptance_broker"]
    assert identity["acceptance_canonical_durable_state_bound"] is True
    assert identity["acceptance_secrets_bound"] is True
    assert broker["acceptance_canonical_durable_state_bound"] is True
    assert broker["acceptance_secrets_bound"] is True
    assert report["workers"]["acceptance_chat"]["deployed"] is True

    # A Worker without its own durable state or its own secret is not ready,
    # even when the sibling acceptance Worker is fully bound.
    _stub_wrangler(monkeypatch, _version_view([
        ("LOCAL_AGENT_BROKER_PEPPER", "secret_text"),
    ]))
    bare = readiness.inventory()
    assert bare["workers"]["acceptance_identity"][
        "acceptance_canonical_durable_state_bound"
    ] is False
    assert bare["workers"]["acceptance_identity"][
        "acceptance_secrets_bound"
    ] is False
    assert bare["workers"]["acceptance_broker"][
        "acceptance_canonical_durable_state_bound"
    ] is False


def test_readiness_reports_derived_facts_only_and_never_proves_pairing(
    monkeypatch
):
    report = _facts(monkeypatch, [
        ("PADIEM_CHAT_SESSION_SECRET", "secret_text"),
        ("PADIEM_CHAT_DB", "d1"),
        ("IDENTITY_AUTHORITY_SERVICE", "service"),
    ])
    rendered = json.dumps(report, ensure_ascii=False)
    # Names and kinds collapse into booleans; no raw binding or account text.
    assert "PADIEM_CHAT_SESSION_SECRET" not in rendered
    assert "secret_text" not in rendered
    assert "fedcba98-7654-3210-acde-1234567890ab" not in rendered
    assert report["workers"]["acceptance_chat"][
        "acceptance_session_secret_bound"
    ] is True
    assert report["actual_owner_windows_pairing_proven"] is False
    assert report["changes_made"] is False


def test_owner_local_manifest_reports_only_bounded_booleans(monkeypatch, tmp_path):
    overlay = tmp_path / "wrangler.connector-acceptance-4139.local.toml"
    monkeypatch.setattr(readiness, "OWNER_OVERLAY", overlay)

    assert readiness._owner_local_overlay() == {"present": False}

    overlay.write_text(
        'name = "padiem-chat-connector-acceptance-4139"\n'
        'workers_dev = false\n\n'
        '[vars]\nPADIEM_CHAT_AUTH_MODE = "password"\n\n'
        '[[d1_databases]]\nbinding = "PADIEM_CHAT_DB"\n'
        'database_name = "padiem-connector-acceptance-4139"\n'
        'database_id = "fedcba98-7654-3210-acde-1234567890ab"\n',
        encoding="utf-8",
    )
    facts = readiness._owner_local_overlay()
    assert facts == {
        "present": True, "readable": True, "password_auth_selected": True,
        "exactly_one_d1_bound": True, "public_route_published": False,
    }
    assert "fedcba98-7654-3210-acde-1234567890ab" not in json.dumps(facts)


def test_a_published_https_route_is_reported_as_an_unauthorized_blocker(
    monkeypatch, tmp_path
):
    overlay = tmp_path / "wrangler.connector-acceptance-4139.local.toml"
    overlay.write_text(
        'name = "padiem-chat-connector-acceptance-4139"\n'
        'workers_dev = false\n'
        'routes = [{ pattern = "connector-acceptance.padiem.net" }]\n\n'
        '[vars]\nPADIEM_CHAT_AUTH_MODE = "password"\n\n'
        '[[d1_databases]]\nbinding = "PADIEM_CHAT_DB"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(readiness, "OWNER_OVERLAY", overlay)
    report = _facts(monkeypatch, [])
    assert report["acceptance_owner_local_manifest"]["public_route_published"] is True
    assert (
        "acceptance_https_route_published_without_authorization"
        in report["blocking_facts"]
    )


def test_source_acceptance_profiles_still_publish_no_route():
    isolated = tomllib.loads(ACCEPTANCE_CHAT.read_text(encoding="utf-8"))
    assert "route" not in isolated and "routes" not in isolated
    for path in (IDENTITY_ACCEPTANCE, BROKER_ACCEPTANCE):
        stage = json.loads(path.read_text(encoding="utf-8"))
        assert "routes" not in stage