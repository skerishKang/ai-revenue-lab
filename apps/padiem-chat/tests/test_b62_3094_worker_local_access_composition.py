"""#3094 — real-path tests: worker composition seam → /api/claw/local-access.

CENTRAL blocker remediation: the earlier evidence composed the projection
source directly into ``create_app(..., claw_local_access_source=fake)``, which
proved the route but never proved that a deployable worker runtime could serve
a real projection. These tests start where the deployed worker actually starts
(``worker.py`` composition root lines, mirrored verbatim below), supply the
approved trusted #3080 broker-authority boundary at the trusted binding, and
then call the real authenticated route.

    worker.py composition root (trusted binding resolution)
        -> build_claw_local_access_source_with_diagnostic(env)
        -> CanonicalClawLocalAccessTruthSource (ONLINE decided by #3080 only)
        -> app.state.claw_local_access_source
        -> GET /api/claw/local-access  (owner-scoped, read-only, opaque)

The trusted boundary stand-in implements the one port protocol the canonical
source may read; the canonical device facts it hands over are real
``kagent`` contracts validated by their own constructors, so the #3080
``project_server_backed_online_binding`` decision exercised here is the real
authority decision, not a re-implementation.

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
    LOCAL_ACCESS_DIAG_CONSTRUCTION_FAILED,
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
from kagent.local_agent_control_plane_runtime import ControlPlaneHeartbeatReceipt
from kagent.local_agent_pairing import DeviceBinding, DeviceLifecycle, DeviceSession

APP_ROOT = Path(__file__).resolve().parents[1]
WORKER_PATH = APP_ROOT / "worker.py"

BASE_URL = "https://chat.example.test"
OWNER_A = "usr_3094_owner_a"
OWNER_B = "usr_3094_owner_b"
CONVERSATION_ID = "conv_3094_01"
ACCOUNT_REF_A = "acct_3094_owner_a"
WORKSPACE_REF = "ws_3094"
DEVICE_ID = "dev_3094_1"
BINDING_REF = "bind_3094_1"
SESSION_ID = "sess_3094_1"
CREDENTIAL_REF = "cred_ref_3094_1_internal"
DESKTOP_HANDOFF = "padiem://local-handoff/AgA1opaque+token==value-3094"

REASON_UNCONFIGURED = LOCAL_ACCESS_UNCONFIGURED_REASON
REASON_SOURCE_FAILED = "local_access_source_failed"

BROKER_AUTHORITY_BINDING_NAME = "LOCAL_AGENT_BROKER_AUTHORITY_SERVICE"


# ---------------------------------------------------------------------------
# Canonical #3080 device facts (real kagent contracts, real validation)
# ---------------------------------------------------------------------------


def _canonical_facts(
    *,
    binding_state: DeviceLifecycle = DeviceLifecycle.PAIRED_OFFLINE,
    broken_session_correlation: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """One correlated set of canonical device facts owned by #3080.

    ``broken_session_correlation`` hands the source a heartbeat that does not
    belong to the session, which the #3080 ONLINE projection must refuse.
    """

    now = now or datetime.now(timezone.utc)
    issued = now - timedelta(minutes=5)
    session = DeviceSession(
        session_id=SESSION_ID,
        device_id=DEVICE_ID,
        binding_ref=BINDING_REF,
        account_ref=ACCOUNT_REF_A,
        workspace_ref=WORKSPACE_REF,
        issued_at=issued,
        expires_at=now + timedelta(minutes=55),
    )
    heartbeat = ControlPlaneHeartbeatReceipt(
        session_id="sess_unrelated_3094" if broken_session_correlation else SESSION_ID,
        binding_ref=BINDING_REF,
        device_id=DEVICE_ID,
        account_ref=ACCOUNT_REF_A,
        workspace_ref=WORKSPACE_REF,
        credential_generation=1,
        last_seen_at=now - timedelta(seconds=10),
        session_expires_at=session.expires_at,
    )
    binding = DeviceBinding(
        device_id=DEVICE_ID,
        binding_ref=BINDING_REF,
        account_ref=ACCOUNT_REF_A,
        workspace_ref=WORKSPACE_REF,
        credential_ref=CREDENTIAL_REF,
        credential_generation=1,
        issued_at=issued,
        credential_expires_at=now + timedelta(days=30),
        state=binding_state,
    )
    return {
        "binding": binding,
        "session": session,
        "heartbeat": heartbeat,
        "device_name": "Padiem-Desktop-3094",
        "platform": "win32",
        "run_id": "run_3094_01",
        "task_id": "task_3094_01",
        "requires_local_access": True,
        "required_capabilities": ["local_computer"],
        "desktop_installed": True,
        "handoff_value": DESKTOP_HANDOFF,
        "handoff_conversation_id": CONVERSATION_ID,
        # Fields the trusted boundary may internally hold but that must never
        # reach a browser response (closed response allowlist proof material).
        "internal_credential_material": "raw-device-secret-must-not-leak-3094",
    }


class TrustedBrokerAuthorityBoundary:
    """Stand-in for the approved #3080 broker-authority port at the binding.

    It owns canonical device facts server-side, keyed by the server-derived
    owner id the route passes in, and exposes exactly the one port protocol the
    canonical source may read. It records every read so tests can prove the
    owner scope came from server identity only.
    """

    configured = True

    def __init__(self, per_owner: dict[str, Any]) -> None:
        self.per_owner = per_owner
        self.calls: list[dict[str, Any]] = []

    def device_truth(self, *, owner_id: str, conversation_id: str, now: datetime) -> Any:
        self.calls.append(
            {"owner_id": owner_id, "conversation_id": conversation_id, "now": now}
        )
        factory = self.per_owner.get(owner_id)
        if factory is None:
            return None
        return factory(now)


class RawServiceBindingWithoutPort:
    """What a deployed service binding actually is today: fetch-only."""

    configured = True

    def fetch(self, request: Any) -> Any:  # pragma: no cover - never called
        raise AssertionError("a fetch-only binding must never be composed as a port")


class HostilePort:
    """A port whose attribute access itself fails: composition must contain it."""

    @property
    def device_truth(self) -> Any:
        raise RuntimeError("port internals exploded with a storage path /secret/path")


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
    composition lines for the local-access source. Returns the pieces tests
    need, including what the default state was before composition."""

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


def _owner_env(*, per_owner: dict[str, Any]) -> dict[str, Any]:
    boundary = TrustedBrokerAuthorityBoundary(per_owner=per_owner)
    return {BROKER_AUTHORITY_BINDING_NAME: boundary, "__boundary__": boundary}


def _env_boundary(env: dict[str, Any]) -> TrustedBrokerAuthorityBoundary:
    return env["__boundary__"]


# ---------------------------------------------------------------------------
# Composition seam itself
# ---------------------------------------------------------------------------


def test_worker_seam_composes_the_canonical_source_from_a_trusted_boundary() -> None:
    env = _owner_env(
        per_owner={OWNER_A: lambda now: _canonical_facts(now=now)},
    )
    app, default_source, source, diagnostic, _settings_unused = _compose_app_from_worker_seam(env=env)
    assert diagnostic is None
    assert isinstance(source, CanonicalClawLocalAccessTruthSource)
    assert source.configured is True
    # The app factory default was the fail-closed unconfigured source; the
    # worker composition root replaced it from the trusted boundary.
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


def test_a_fetch_only_service_binding_is_never_composed_as_the_trusted_port() -> None:
    _, _, source, diagnostic, _app = _compose_app_from_worker_seam(
        env={BROKER_AUTHORITY_BINDING_NAME: RawServiceBindingWithoutPort()}
    )
    assert source is None
    assert diagnostic == LOCAL_ACCESS_DIAG_PORT_INCOMPATIBLE


def test_a_hostile_port_fails_closed_with_a_bounded_diagnostic_only() -> None:
    _, _, source, diagnostic, _app = _compose_app_from_worker_seam(
        env={BROKER_AUTHORITY_BINDING_NAME: HostilePort()}
    )
    assert source is None
    assert diagnostic == LOCAL_ACCESS_DIAG_PORT_INCOMPATIBLE
    assert diagnostic in {
        LOCAL_ACCESS_DIAG_BOUNDING_ABSENT,
        LOCAL_ACCESS_DIAG_PORT_INCOMPATIBLE,
        LOCAL_ACCESS_DIAG_CONSTRUCTION_FAILED,
    }


def test_the_worker_composition_root_wires_the_local_access_seam() -> None:
    worker_source = WORKER_PATH.read_text(encoding="utf-8")
    assert "build_claw_local_access_source_with_diagnostic(self.env)" in worker_source
    assert "if claw_local_access_source is not None:" in worker_source
    assert "_worker_app.state.claw_local_access_source = claw_local_access_source" in worker_source
    # Worker-native composition: trusted bindings only, never os.environ.
    composition_source = (
        APP_ROOT / "app" / "claw_local_access_composition.py"
    ).read_text(encoding="utf-8")
    assert "os.environ" not in composition_source


# ---------------------------------------------------------------------------
# Real path: trusted boundary → canonical source → authenticated route
# ---------------------------------------------------------------------------


def test_server_online_projects_as_web_connected_on_the_real_path() -> None:
    env = _owner_env(per_owner={OWNER_A: lambda now: _canonical_facts(now=now)})
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
    assert projection["desktopInstalled"] is True
    # HANDOFF_FORWARDED_OPAQUELY: the upstream authority's value, byte-for-byte.
    assert projection["handoff"]["value"] == DESKTOP_HANDOFF
    assert projection["handoff"]["conversationId"] == CONVERSATION_ID
    # The boundary was read with the server-derived owner id only.
    boundary = _env_boundary(env)
    assert len(boundary.calls) == 1
    assert boundary.calls[0]["owner_id"] == OWNER_A
    assert boundary.calls[0]["conversation_id"] == CONVERSATION_ID


def test_online_is_decided_by_the_3080_projection_not_by_b62() -> None:
    # A heartbeat unrelated to the session must make the #3080 ONLINE
    # projection refuse; B62 then reports the binding's own canonical state
    # (paired_offline) and never invents an online claim of its own.
    env = _owner_env(
        per_owner={
            OWNER_A: lambda now: _canonical_facts(
                broken_session_correlation=True, now=now
            )
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


def test_revoked_device_fails_closed_and_forwards_no_handoff() -> None:
    env = _owner_env(
        per_owner={
            OWNER_A: lambda now: _canonical_facts(
                binding_state=DeviceLifecycle.REVOKED, now=now
            )
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


def test_absent_canonical_truth_for_the_owner_fails_closed() -> None:
    # The trusted boundary knows no device for this owner: the source asserts
    # nothing and the route answers available=false with a bounded reason.
    env = _owner_env(per_owner={OWNER_A: lambda now: _canonical_facts(now=now)})
    response, *_ = _get(env=env, user_id=OWNER_B, params={"conversationId": CONVERSATION_ID})
    body = response.json()
    assert body["available"] is False
    assert body["reason"] == REASON_SOURCE_FAILED
    assert body["projection"]["device"] is None


def test_a_boundary_payload_without_canonical_facts_asserts_nothing() -> None:
    env = _owner_env(per_owner={OWNER_A: lambda now: {"note": "not canonical"}})
    response, *_ = _get(env=env, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    body = response.json()
    assert body["available"] is False
    assert body["reason"] == REASON_SOURCE_FAILED
    assert body["projection"]["device"] is None


def test_an_unrecognised_canonical_state_fails_closed() -> None:
    env = _owner_env(
        per_owner={
            OWNER_A: lambda now: {
                **_canonical_facts(now=now),
                "binding": "not-a-canonical-binding",
            },
        },
    )
    response, *_ = _get(env=env, user_id=OWNER_A, params={"conversationId": CONVERSATION_ID})
    # Not a canonical DeviceBinding instance -> the source asserts nothing.
    body = response.json()
    assert body["available"] is False


# ---------------------------------------------------------------------------
# Owner scope and secret hygiene on the real path
# ---------------------------------------------------------------------------


def test_owner_scope_comes_from_server_identity_and_browser_authority_is_ignored() -> None:
    env = _owner_env(per_owner={OWNER_A: lambda now: _canonical_facts(now=now)})
    # Owner B is signed in and supplies owner A's account/workspace refs as
    # browser query parameters. The route must pass the session identity only.
    response, *_ = _get(
        env=env,
        user_id=OWNER_B,
        params={
            "conversationId": CONVERSATION_ID,
            "account_ref": ACCOUNT_REF_A,
            "workspace_ref": WORKSPACE_REF,
        },
    )
    body = response.json()
    # Owner B has no device truth: fail closed, no owner A device leaked.
    assert body["available"] is False
    assert body["projection"]["device"] is None
    boundary = _env_boundary(env)
    assert len(boundary.calls) == 1
    call = boundary.calls[0]
    assert call["owner_id"] == OWNER_B
    assert set(call) == {"owner_id", "conversation_id", "now"}
    # The response carries no account/workspace authority fields at all.
    flat = json.dumps(body)
    assert ACCOUNT_REF_A not in flat
    assert WORKSPACE_REF not in flat


def test_no_internal_credential_or_session_material_reaches_the_response() -> None:
    env = _owner_env(per_owner={OWNER_A: lambda now: _canonical_facts(now=now)})
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
    assert CREDENTIAL_REF not in flat
    assert SESSION_ID not in flat
    assert BINDING_REF not in flat
    assert DEVICE_ID not in flat
    assert "raw-device-secret-must-not-leak-3094" not in flat
    assert "credential" not in flat.lower()


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
    assert claw_local_access_composition.PRODUCTION_MUTATION is False
