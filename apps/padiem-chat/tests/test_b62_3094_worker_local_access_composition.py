"""#3094 — real-path tests: worker composition seam → /api/claw/local-access.

The trusted boundary in these tests implements the **actual binding surface**
the canonical Local Agent broker Worker exposes: an async ``device_truth(payload)``
RPC returning the broker's bounded envelope (``ok`` / ``available`` /
``device_truth`` facts). That is the exact API added to
``packages/padiem-control-plane/local_agent_broker_worker.py`` — the dedicated
end-to-end test instantiates that real entrypoint (see
``test_b62_3094_canonical_broker_device_truth_integration.py``); this file pins
the seam behaviour and every fail-closed branch around it.

    worker.py composition root (trusted binding resolution)
        -> build_claw_local_access_source_with_diagnostic(env)
        -> BrokerAuthorityDeviceTruthPort(binding.device_truth RPC)
        -> CanonicalClawLocalAccessTruthSource (ONLINE decided by #3080 only)
        -> app.state.claw_local_access_source
        -> GET /api/claw/local-access  (owner-scoped, read-only, opaque)

    REAL_LOCAL_ACCESS_PROJECTION_SOURCE=YES (proved on the real path)
    SERVER_ONLINE_TO_WEB_CONNECTED=YES (proved on the real path)
    OFFLINE_OR_UNKNOWN_FAIL_CLOSED=YES (proved on the real path)
    OWNER_SCOPE_FROM_SERVER_IDENTITY=YES
    HANDOFF_FORWARDED_OPAQUELY=YES
    SECOND_DEVICE_LIFECYCLE_AUTHORITY=0
    RAW_CREDENTIAL_PROJECTION=0
    PRODUCTION_MUTATION=0
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx

from app.auth import SESSION_COOKIE, create_session_token
from app.claw_local_access_composition import (
    LOCAL_ACCESS_DIAG_BOUNDING_ABSENT,
    LOCAL_ACCESS_DIAG_PORT_INCOMPATIBLE,
    build_claw_local_access_source_with_diagnostic,
)
from app.claw_local_access_routes import (
    CLAW_LOCAL_ACCESS_PATH,
    LOCAL_ACCESS_UNCONFIGURED_REASON,
)
from app.claw_local_access_source import CanonicalClawLocalAccessTruthSource
from app.config import Settings
from app.main import create_app
from kagent.local_agent_pairing import DeviceLifecycle

APP_ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = APP_ROOT / "worker.py"

BASE_URL = "https://chat.example.test"
# The B62 session identity (usr_*) is the only scope key this seam forwards:
# the composition passes the authenticated owner id to the broker unchanged as
# the device's account_ref, exactly as the composed pairing path registers it.
# No mapping is invented here — a browser-supplied account/workspace ref is
# never accepted (see test_owner_scope...).
OWNER_A = "usr_3094_owner_a"
OWNER_B = "usr_3094_owner_b"
WORKSPACE_REF = "ws_3094"
CONVERSATION_ID = "conv_3094_01"
DESKTOP_HANDOFF = "padiem://local-handoff/AgA1opaque+token==value-3094"

REASON_UNCONFIGURED = LOCAL_ACCESS_UNCONFIGURED_REASON
REASON_SOURCE_FAILED = "local_access_source_failed"

BROKER_AUTHORITY_BINDING_NAME = "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"


def _broker_device_truth(
    *,
    now: datetime,
    canonical_state: str = "paired_offline",
    with_session: bool = True,
    last_seen_offset_seconds: int = 10,
    handoff_value: str | None = DESKTOP_HANDOFF,
    desktop_installed: bool | None = None,
) -> dict[str, Any]:
    """The broker's device_truth facts shape for one live device (#3080-owned).

    Timestamps are built from ``now`` exactly the way the canonical broker's
    records are: a session opened ten minutes ago with a one-hour-ish TTL and a
    recent server-owned heartbeat. ``canonical_state`` is whatever the broker's
    own pure rename produced (``paired_offline`` / ``credential_expired`` /
    ``revoked`` — never ``online``).
    """

    issued = now - timedelta(minutes=10)
    session_expires = issued + timedelta(minutes=55)
    facts: dict[str, Any] = {
        "canonical_state": canonical_state,
        "binding": {
            "binding_ref": "bind_3094_1",
            "device_id": "dev_3094_1",
            "account_ref": OWNER_A,
            "workspace_ref": WORKSPACE_REF,
            "credential_generation": 1,
            "issued_at": (issued - timedelta(days=1)).isoformat(),
            "credential_expires_at": (now + timedelta(days=30)).isoformat(),
            "credential_digest_exposed": False,
            "raw_device_credential": False,
        },
        "session": None,
        "heartbeat_last_seen_at": None,
    }
    if with_session:
        facts["session"] = {
            "session_id": "sess_3094_1",
            "binding_ref": "bind_3094_1",
            "device_id": "dev_3094_1",
            "account_ref": OWNER_A,
            "workspace_ref": WORKSPACE_REF,
            "credential_generation": 1,
            "issued_at": issued.isoformat(),
            "expires_at": session_expires.isoformat(),
            "raw_session_secret": False,
        }
        facts["heartbeat_last_seen_at"] = (issued + timedelta(seconds=last_seen_offset_seconds)).isoformat()
    if handoff_value is not None:
        facts["handoff_value"] = handoff_value
    if desktop_installed is not None:
        facts["desktop_installed"] = desktop_installed
    return facts


class TrustedBrokerAuthorityBinding:
    """Stand-in for the canonical broker Worker service binding.

    It exposes exactly the surface the composition consumes — the real
    ``device_truth(payload)`` RPC shape of
    ``packages/padiem-control-plane/local_agent_broker_worker.py::Default`` —
    and answers with the broker's bounded envelope, owner-scoped by the
    ``account_ref`` the caller (server identity) passed. It records every read.
    """

    def __init__(self, per_account: dict[str, dict[str, Any] | None]) -> None:
        self.per_account = per_account
        self.calls: list[dict[str, Any]] = []

    async def device_truth(self, payload: dict) -> dict:
        self.calls.append(dict(payload))
        account_ref = payload.get("account_ref")
        facts = self.per_account.get(account_ref, "missing")
        if facts == "missing" or facts is None:
            return {"ok": True, "available": False, "reason": "no_device_binding"}
        return {"ok": True, "available": True, "device_truth": facts}


class RawServiceBindingWithoutPort:
    """What a deployed service binding is when it is not the broker: fetch-only."""

    def fetch(self, request: Any) -> Any:  # pragma: no cover - never called
        raise AssertionError("a fetch-only binding must never be composed as a port")


class HostileBinding:
    """A binding whose attribute access itself fails: composition must contain it."""

    @property
    def device_truth(self) -> Any:
        raise RuntimeError("binding internals exploded with a storage path /secret/path")


# ---------------------------------------------------------------------------
# Real composition helpers (worker.py parity)
# ---------------------------------------------------------------------------


def _settings() -> Settings:
    return Settings.from_values(
        runtime_mode="mock",
        auth_mode="password",
        public_base_url=BASE_URL,
        session_secret="claw-3094-worker-composition-session-secret-not-real",
        session_max_age_seconds=3600,
    )


def _compose_app_from_worker_seam(
    *,
    env: dict[str, Any],
) -> tuple[Any, Any, Any, Any, Any]:
    """create_app() exactly like worker.py calls it, then the exact worker.py
    composition lines for the local-access source."""

    settings = _settings()
    app = create_app(settings, history_store=MagicMock())
    default_source = app.state.claw_local_access_source
    # --- verbatim worker.py composition root lines ---
    source, diagnostic = build_claw_local_access_source_with_diagnostic(env)
    if source is not None:
        app.state.claw_local_access_source = source
    # --- end verbatim lines ---
    return app, default_source, source, diagnostic, settings


async def _authorized_get(
    app: Any,
    settings: Settings,
    *,
    user_id: str,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as client:
        client.cookies.set(SESSION_COOKIE, create_session_token(settings, user_id))
        return await client.get(CLAW_LOCAL_ACCESS_PATH, params=params)


def _get(
    *,
    env: dict[str, Any],
    user_id: str,
    params: dict[str, str] | None = None,
) -> tuple[httpx.Response, Any, Any, Any, str | None]:
    app, default_source, source, diagnostic, settings = _compose_app_from_worker_seam(env=env)
    response = asyncio.run(
        _authorized_get(app, settings, user_id=user_id, params=params)
    )
    return response, default_source, source, diagnostic, app


def _owner_env(*, per_account: dict[str, dict[str, Any] | None]) -> dict[str, Any]:
    binding = TrustedBrokerAuthorityBinding(per_account=per_account)
    return {BROKER_AUTHORITY_BINDING_NAME: binding, "__binding__": binding}


def _env_binding(env: dict[str, Any]) -> TrustedBrokerAuthorityBinding:
    return env["__binding__"]


def _live_owner_facts(now: datetime | None = None) -> dict[str, Any]:
    return _broker_device_truth(now=now or datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Composition seam itself
# ---------------------------------------------------------------------------


def test_worker_seam_composes_the_canonical_source_from_a_trusted_broker_binding() -> None:
    env = _owner_env(per_account={OWNER_A: _live_owner_facts()})
    app, default_source, source, diagnostic, _settings_unused = _compose_app_from_worker_seam(env=env)
    assert diagnostic is None
    assert isinstance(source, CanonicalClawLocalAccessTruthSource)
    assert source.configured is True
    # The app factory default was the fail-closed unconfigured source; the
    # worker composition root replaced it from the trusted binding.
    assert default_source is not app.state.claw_local_access_source
    assert app.state.claw_local_access_source is source


def test_deployed_shape_without_a_trusted_boundary_stays_fail_closed_unconfigured() -> None:
    # Today's deploy: the binding does not resolve.
    app, default_source, source, diagnostic, _settings_unused = _compose_app_from_worker_seam(env={})
    assert source is None
    assert diagnostic == LOCAL_ACCESS_DIAG_BOUNDING_ABSENT
    # The app keeps the fail-closed unconfigured source installed by the
    # factory: no guessed device state can appear.
    assert app.state.claw_local_access_source is default_source
    response, *_ = _get(env={}, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    body = response.json()
    assert response.status_code == 200
    assert body["ok"] is True
    assert body["available"] is False
    assert body["reason"] == REASON_UNCONFIGURED
    assert body["projection"]["device"] is None
    assert body["projection"]["handoff"] == {"kind": "deep_link", "unavailableReason": "absent"}


def test_a_fetch_only_service_binding_is_never_composed_as_the_broker_port() -> None:
    _, _, source, diagnostic, _app = _compose_app_from_worker_seam(
        env={BROKER_AUTHORITY_BINDING_NAME: RawServiceBindingWithoutPort()}
    )
    assert source is None
    assert diagnostic == LOCAL_ACCESS_DIAG_PORT_INCOMPATIBLE


def test_a_hostile_binding_fails_closed_with_a_bounded_diagnostic_only() -> None:
    _, _, source, diagnostic, _app = _compose_app_from_worker_seam(
        env={BROKER_AUTHORITY_BINDING_NAME: HostileBinding()}
    )
    assert source is None
    assert diagnostic == LOCAL_ACCESS_DIAG_PORT_INCOMPATIBLE
    assert diagnostic in {
        LOCAL_ACCESS_DIAG_BOUNDING_ABSENT,
        LOCAL_ACCESS_DIAG_PORT_INCOMPATIBLE,
        "local_access_source_construction_failed",
    }


def test_the_worker_composition_root_wires_the_local_access_seam() -> None:
    worker_source = WORKER_PATH.read_text(encoding="utf-8")
    assert "build_claw_local_access_source_with_diagnostic(self.env)" in worker_source
    assert "if claw_local_access_source is not None:" in worker_source
    assert "_worker_app.state.claw_local_access_source = claw_local_access_source" in worker_source
    # Worker-native composition: trusted bindings only, never a process env.
    composition_source = (
        APP_ROOT / "app" / "claw_local_access_composition.py"
    ).read_text(encoding="utf-8")
    assert "os.environ" not in composition_source
    # The consumed API is the canonical broker's device_truth RPC.
    assert "device_truth" in composition_source


# ---------------------------------------------------------------------------
# Real path: trusted binding → canonical source → authenticated route
# ---------------------------------------------------------------------------


def test_server_online_projects_as_web_connected_on_the_real_path() -> None:
    env = _owner_env(per_account={OWNER_A: _live_owner_facts()})
    response, *_ = _get(env=env, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["available"] is True
    projection = body["projection"]
    device = projection["device"]
    # SERVER_ONLINE_TO_WEB_CONNECTED: canonical online -> CONNECTED, usable.
    assert device["canonicalState"] == DeviceLifecycle.ONLINE.value
    assert device["state"] == "CONNECTED"
    assert device["usable"] is True
    assert device["unrecognised"] is False
    assert projection["requiresLocalAccess"] is True
    # HANDOFF_FORWARDED_OPAQUELY: the upstream authority's value, byte-for-byte.
    assert projection["handoff"]["value"] == DESKTOP_HANDOFF
    # The broker was read with the server-derived identity only.
    binding = _env_binding(env)
    assert len(binding.calls) == 1
    assert binding.calls[0] == {"account_ref": OWNER_A}


def test_online_is_decided_by_the_3080_projection_not_by_b62() -> None:
    # A server-owned heartbeat outside the session lifetime must make the
    # #3080 ONLINE projection refuse; B62 then reports the broker's own
    # canonical state (paired_offline) and never invents an online claim.
    now = datetime.now(timezone.utc)
    env = _owner_env(
        per_account={
            OWNER_A: _broker_device_truth(now=now, last_seen_offset_seconds=-7200),
        },
    )
    response, *_ = _get(env=env, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    body = response.json()
    assert body["available"] is True
    device = body["projection"]["device"]
    assert device["canonicalState"] == DeviceLifecycle.PAIRED_OFFLINE.value
    assert device["state"] == "OFFLINE"
    assert device["usable"] is False
    # No usable device -> the handoff is not forwarded either.
    assert "value" not in body["projection"]["handoff"]


def test_a_stale_session_cannot_project_online() -> None:
    # The broker reports a session that expired: the #3080 rule refuses ONLINE.
    now = datetime.now(timezone.utc)
    env = _owner_env(
        per_account={
            OWNER_A: _broker_device_truth(
                now=now,
                last_seen_offset_seconds=-40 * 60,
            ),
        },
    )
    response, *_ = _get(env=env, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    device = response.json()["projection"]["device"]
    assert device["state"] == "OFFLINE"
    assert device["usable"] is False


def test_revoked_device_fails_closed_and_forwards_no_handoff() -> None:
    now = datetime.now(timezone.utc)
    env = _owner_env(
        per_account={
            OWNER_A: _broker_device_truth(
                now=now,
                canonical_state="revoked",
                with_session=False,
            ),
        },
    )
    response, *_ = _get(env=env, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    body = response.json()
    device = body["projection"]["device"]
    assert device["canonicalState"] == DeviceLifecycle.REVOKED.value
    assert device["state"] == "REVOKED"
    assert device["usable"] is False
    assert device["revoked"] is True
    assert "value" not in body["projection"]["handoff"]


def test_credential_expired_cannot_be_resurrected_online_by_a_current_session() -> None:
    # The lifecycle invariant: only a broker-reported paired_offline device may
    # attempt the #3080 ONLINE projection. A credential_expired report with a
    # still-current session and heartbeat must stay fail-closed — the old
    # reconstruction (hard-coded PAIRED_OFFLINE) would have let the rule
    # promote it to ONLINE / CONNECTED.
    now = datetime.now(timezone.utc)
    env = _owner_env(
        per_account={
            OWNER_A: _broker_device_truth(
                now=now,
                canonical_state="credential_expired",
                with_session=True,
            ),
        },
    )
    response, *_ = _get(env=env, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    body = response.json()
    assert body["available"] is True
    device = body["projection"]["device"]
    assert device["canonicalState"] == DeviceLifecycle.CREDENTIAL_EXPIRED.value
    assert device["state"] == "ACTION_REQUIRED"
    assert device["usable"] is False
    assert device["expired"] is True
    # The facts were current, but ONLINE is unreachable from this state.
    assert device["state"] != "CONNECTED"
    assert "value" not in body["projection"]["handoff"]


def test_absent_canonical_truth_for_the_owner_fails_closed() -> None:
    # The broker knows no device for this owner: available=false, no device.
    env = _owner_env(per_account={OWNER_A: _live_owner_facts()})
    response, *_ = _get(env=env, user_id=OWNER_B, params={"conversationId": CONVERSATION_ID})
    body = response.json()
    assert body["available"] is False
    assert body["reason"] == REASON_SOURCE_FAILED
    assert body["projection"]["device"] is None


def test_a_refused_or_malformed_broker_envelope_asserts_nothing() -> None:
    refused = _owner_env(per_account={OWNER_A: None})
    response, *_ = _get(env=refused, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    body = response.json()
    assert body["available"] is False

    malformed = _owner_env(per_account={OWNER_A: {"note": "not the broker envelope"}})
    response, *_ = _get(env=malformed, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    assert response.json()["available"] is False

    no_facts = _owner_env(
        per_account={OWNER_A: {"ok": True, "available": True, "device_truth": None}}
    )
    response, *_ = _get(env=no_facts, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    assert response.json()["available"] is False


def test_an_unknown_broker_canonical_state_fails_closed() -> None:
    # Even a broker answer outside the narrow known vocabulary (or one that
    # illegally claims "online") asserts nothing: ONLINE comes only from the
    # #3080 projection rule, never from a vocabulary string.
    for smuggled_state in ("online", "mystery_state_9000"):
        env = _owner_env(
            per_account={
                OWNER_A: _broker_device_truth(
                    now=datetime.now(timezone.utc),
                    canonical_state=smuggled_state,
                )
            },
        )
        response, *_ = _get(env=env, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
        assert response.json()["available"] is False


def test_owner_scope_comes_from_server_identity_and_browser_authority_is_ignored() -> None:
    env = _owner_env(per_account={OWNER_A: _live_owner_facts()})
    # Owner B is signed in and supplies owner A's account/workspace refs as
    # browser query parameters. The route must pass the session identity only.
    response, *_ = _get(
        env=env,
        user_id=OWNER_B,
        params={
            "conversationId": CONVERSATION_ID,
            "account_ref": OWNER_A,
            "workspace_ref": WORKSPACE_REF,
        },
    )
    body = response.json()
    # Owner B has no device truth: fail closed, no owner A device leaked.
    assert body["available"] is False
    assert body["projection"]["device"] is None
    binding = _env_binding(env)
    assert len(binding.calls) == 1
    assert binding.calls[0] == {"account_ref": OWNER_B}
    # The response carries no account/workspace authority fields at all.
    flat = json.dumps(body)
    assert OWNER_A not in flat
    assert WORKSPACE_REF not in flat


def test_no_internal_credential_or_session_material_reaches_the_response() -> None:
    env = _owner_env(per_account={OWNER_A: _live_owner_facts()})
    response, *_ = _get(env=env, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    body = response.json()
    # Closed response allowlist, verified on the real path.
    assert set(body) == {"ok", "available", "projectionVersion", "reason", "projection"}
    projection = body["projection"]
    assert set(projection) == {
        "contractVersion",
        "conversationId",
        "runId",
        "taskId",
        "requiresLocalAccess",
        "requiredCapabilities",
        "desktopInstalled",
        "device",
        "handoff",
    }
    flat = json.dumps(body)
    assert "sess_3094_1" not in flat
    assert "bind_3094_1" not in flat
    assert "dev_3094_1" not in flat
    assert "credential" not in flat.lower()


def test_desktop_installation_is_never_fabricated() -> None:
    # Without broker evidence of an installed desktop the projection reports
    # not installed (install guidance), never an assumed openable handoff.
    env = _owner_env(per_account={OWNER_A: _live_owner_facts()})
    response, *_ = _get(env=env, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    assert response.json()["projection"]["desktopInstalled"] is False

    evidenced = _owner_env(
        per_account={
            OWNER_A: _broker_device_truth(
                now=datetime.now(timezone.utc),
                desktop_installed=True,
            )
        },
    )
    response, *_ = _get(env=evidenced, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    assert response.json()["projection"]["desktopInstalled"] is True


# ---------------------------------------------------------------------------
# Module contract markers
# ---------------------------------------------------------------------------


def test_source_and_composition_declare_no_second_authority_and_no_mutation() -> None:
    from app import claw_local_access_composition, claw_local_access_source

    assert claw_local_access_source.SECOND_DEVICE_LIFECYCLE_AUTHORITY is False
    assert claw_local_access_source.NEW_LIFECYCLE_STATE_CREATED == 0
    assert claw_local_access_source.HANDOFF_VALUE_MINTED_OR_PARSED is False
    assert claw_local_access_source.OWNER_SCOPE_SOURCE == "server_session_identity_only"
    assert claw_local_access_source.PRODUCTION_MUTATION is False
    assert claw_local_access_composition.FAIL_CLOSED_WHEN_BOUNDARY_ABSENT is True
    assert claw_local_access_composition.COMPOSITION_INPUT_SOURCE == (
        "trusted_worker_bindings_only"
    )
    assert "device_truth" in claw_local_access_composition.CONSUMED_BROKER_API
    assert claw_local_access_composition.PRODUCTION_MUTATION is False
