"""#5080 Android SAF trigger over ASGI + real SQLite D1 history.

The phone is an ordinary canonical Broker device; this lane only substitutes
the folder authority: the SAF set the phone declared, never a browser value.
These tests run the actual Starlette app (routing, middleware, JSON handling)
against a real D1-shaped history database and a Mock Android agent stand-in at
the private Broker boundary.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from app import connector_android_read_routes as routes
from app.auth import SESSION_COOKIE, create_session_token
from app.canonical_connector_enrollment_async_host import (
    CanonicalConnectorEnrollmentAsyncHost,
)
from app.claw_device_directory_routes import (
    CLAW_DEVICE_DIRECTORY_PATH, BrokerDeviceDirectorySource,
)
from app.config import Settings
from app.connector_owner_runtime_mount import ExactOwnerOrigin, OwnerEnrollmentPorts
from app.connector_android_saf_approval_material import saf_read_fingerprint
from app.control_plane_broker_pairing_client import CloudflareCanonicalBrokerPairingClient
from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.history import D1HistoryStore, HistoryError
from app.main import create_app

from test_claw_local_task_result_projection import (
    OWNER_SUBJECT,
    OTHER_SUBJECT,
    _SqliteD1,
    _accounts,
    _conversation_with_run,
)

BASE = "https://chat.example.test"
TENANT_WS = "tenant-ws-android-1"
ACCOUNT = "account-canonical-android-1"
CONNECTOR_WS = "connector-ws-android-1"
DEVICE = "device.android.1"
BINDING = "binding.android.1"
RUN = "run.android.1"
ROOT = "safroot-documents"
FOLDERS = [
    {"root_ref": ROOT, "display_name": "Documents"},
    {"root_ref": "safroot-notes", "display_name": "Notes"},
]
PROFILE = {
    "profile_ref": "profile.android.saf-txt.v1",
    "platform": "android",
    "capabilities": ["local.filesystem.read"],
    "read_suffix": ".txt",
    "folders": FOLDERS,
}

_MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def _open_database(path):
    """Real app migrations; sync-off keeps Windows fsync-per-statement cheap."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = _SqliteD1(path)
    db._connection.execute("PRAGMA synchronous=OFF")
    for migration in sorted(_MIGRATIONS.glob("*.sql")):
        db._connection.executescript(migration.read_text(encoding="utf-8"))
    return db


def _async_noop(payload):
    return {"ok": False, "payload": payload}


def _owner_enrollment_ports():
    identity_binding = SimpleNamespace(**{
        name: _async_noop for name in (
            "grant_connector_enrollment_consent",
            "revoke_connector_enrollment_consent",
            "resolve_connector_enrollment_consent_for_device",
            "bind_connector_enrollment_challenge",
            "authorize_connector_enrollment_redeem",
        )
    })
    broker_binding = SimpleNamespace(**{
        name: _async_noop for name in (
            "issue_enrollment_challenge", "get_enrollment_binding",
            "verify_enrollment_bootstrap", "redeem_enrollment", "revoke_binding",
        )
    })
    identity = CloudflareControlPlaneIdentityAuthority(identity_binding)
    host = CanonicalConnectorEnrollmentAsyncHost(
        identity=identity,
        broker=CloudflareCanonicalBrokerPairingClient(broker_binding),
        credential_handoff=None,
    )
    return OwnerEnrollmentPorts(identity=identity, host=host, csrf=ExactOwnerOrigin())


class FakeIdentity:
    """Mock of the Identity consent authority (no network)."""

    def __init__(self, consent=None, connector_workspace=CONNECTOR_WS):
        self.consent = consent
        self.connector_workspace = connector_workspace
        self.calls = []

    async def resolve_connector_enrollment_consent_for_device(self, *, session_id, device_id):
        self.calls.append(("consent", session_id, device_id))
        if self.consent is None:
            raise RuntimeError("no consent")
        return dict(self.consent)

    async def resolve_connector_workspace(self, *, session_id):
        self.calls.append(("workspace", session_id))
        return self.connector_workspace


_UNSET = object()


class FakeBrokerSource:
    """Mock Android agent's server-side Broker boundary (no network)."""

    configured = True

    def __init__(self, *, device=_UNSET, profile=None):
        self.device = {
            "binding_ref": BINDING, "device_id": DEVICE, "credential_generation": 1,
        } if device is _UNSET else device
        self.profile = profile
        self.resolve_calls = []
        self.enqueues = []

    async def resolve_device_binding(self, *, account_ref, workspace_ref, device_id):
        self.resolve_calls.append((account_ref, workspace_ref, device_id))
        if self.device is None:
            raise IdentityBridgeError(404, "txt_device_unbound", "unbound")
        return dict(self.device)

    async def resolve_android_saf_profile(self, *, account_ref, workspace_ref, device_id, binding_ref):
        self.resolve_calls.append((account_ref, workspace_ref, device_id, binding_ref))
        if self.profile is None:
            raise IdentityBridgeError(503, "android_saf_profile_unavailable", "absent")
        return json.loads(json.dumps(self.profile))

    async def enqueue_txt_read_command(self, *, command, material):
        self.enqueues.append((command, material))
        return {
            "command_id": command["command_id"],
            "run_id": command["run_id"],
            "revision_ref": "revision.android.1",
            "request_fingerprint": command["request_fingerprint"],
        }


def _consent(**overrides):
    value = {
        "device_id": DEVICE, "account_ref": ACCOUNT,
        "workspace_ref": CONNECTOR_WS, "consent_id": "consent.android.1",
        "withdrawn_at": None,
    }
    value.update(overrides)
    return value


def make_env(tmp_path, *, identity=None, source=None, owner=None):
    history = D1HistoryStore(_open_database(tmp_path / "chat.sqlite3"))
    accounts = _accounts(history)
    owner = owner or accounts[OWNER_SUBJECT]
    conversation_id = _conversation_with_run(
        history, owner=owner, run_id=RUN, workspace_id=TENANT_WS,
    )
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="5080-android-trigger-test-not-real-session-secret",
        session_max_age_seconds=3600,
    )
    source = source or FakeBrokerSource(profile=PROFILE)
    identity = identity or FakeIdentity(_consent())
    app = create_app(
        settings,
        history_store=history,
        connector_txt_read_source=source,
        connector_owner_enrollment=_owner_enrollment_ports(),
    )
    app.state.control_plane_identity_authority = identity
    return SimpleNamespace(
        app=app, settings=settings, source=source, identity=identity,
        history=history, owner=owner, conversation_id=conversation_id,
        other=accounts[OTHER_SUBJECT],
    )


@pytest.fixture
def patch_owner_session(monkeypatch):
    async def verified(request):
        del request
        return SimpleNamespace(session_id="session.b54.android.1"), None

    async def workspace(request, uid):
        del request, uid
        return TENANT_WS

    monkeypatch.setattr(routes, "_verified_owner_request", verified)
    monkeypatch.setattr(routes, "_resolve_memory_workspace", workspace)


def call(env, method, path, *, user=None, body=None, params=None,
         signed=True, origin=True, content_type=None):
    user = user or env.owner

    async def perform():
        transport = httpx.ASGITransport(app=env.app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            if signed:
                client.cookies.set(SESSION_COOKIE, create_session_token(env.settings, user))
            headers = {}
            if origin:
                headers["Origin"] = BASE
            else:
                # conftest otherwise attaches a same-origin browser Origin.
                headers["x-test-no-origin"] = "1"
            if method == "GET":
                return await client.get(path, params=params, headers=headers)
            if content_type is not None:
                headers["content-type"] = content_type
                return await client.post(path, content=body, headers=headers)
            return await client.post(path, json=body, headers=headers)

    return asyncio.run(perform())


def read_body(**overrides):
    value = {
        "device_id": DEVICE, "root_ref": ROOT,
        "path_relative": "notes/report.txt", "run_id": RUN, "confirmed": True,
    }
    value.update(overrides)
    return value


def test_saf_read_fingerprint_matches_the_published_android_vector():
    assert saf_read_fingerprint(
        action_id="andact-vector-1",
        run_id="run.android.vector.1",
        device_id="device.android.vector.1",
        root_ref="safroot-documents",
        path_relative="notes/report.txt",
        requested_at="2026-10-19T06:00:00Z",
    ) == "fb438c4de05d28b5c840a7af23b3eab9dbd223139ba92f2c88cfdf050a994e79"


def test_folders_require_session_and_reject_scope_injection(patch_owner_session, tmp_path):
    env = make_env(tmp_path)
    assert call(env, "GET", routes.CONNECTOR_ANDROID_FOLDERS_PATH,
                params={"device_id": DEVICE}, signed=False).status_code == 401
    response = call(
        env, "GET", routes.CONNECTOR_ANDROID_FOLDERS_PATH,
        params={"device_id": DEVICE, "account_ref": "victim"},
    )
    assert response.status_code == 400
    assert env.source.resolve_calls == []
    # The post route is cookie-authenticated, so the central same-origin guard
    # must deny a missing Origin before any broker call.
    denied = call(env, "POST", routes.CONNECTOR_ANDROID_READ_REQUEST_PATH,
                  body=read_body(), origin=False)
    assert denied.status_code == 403
    assert env.source.enqueues == []


def test_folders_are_only_the_phone_declared_set(patch_owner_session, tmp_path):
    env = make_env(tmp_path)
    response = call(env, "GET", routes.CONNECTOR_ANDROID_FOLDERS_PATH,
                    params={"device_id": DEVICE})
    assert response.status_code == 200
    assert response.json() == {
        "ok": True, "available": True,
        "device": {
            "device_id": DEVICE, "platform": "android",
            "profile_ref": "profile.android.saf-txt.v1",
            "capabilities": ["local.filesystem.read"],
            "read_suffix": ".txt", "folders": FOLDERS,
        },
    }
    assert "content://" not in response.text
    assert env.source.resolve_calls[-1] == (ACCOUNT, CONNECTOR_WS, DEVICE, BINDING)


def test_confirmed_read_dispatches_android_material_and_binds_the_run(
    patch_owner_session, tmp_path,
):
    env = make_env(tmp_path)
    response = call(env, "POST", routes.CONNECTOR_ANDROID_READ_REQUEST_PATH,
                    body=read_body())
    assert response.status_code == 200
    result = response.json()
    assert result["ok"] is True
    assert result["conversation_id"] == env.conversation_id
    assert result["command"]["run_id"] == RUN
    assert "content://" not in response.text
    assert "safroot" not in json.dumps(result)

    command, material = env.source.enqueues[0]
    assert command["binding_ref"] == BINDING
    assert material["root_ref"] == ROOT
    assert material["argv"] == []
    assert material["shell_authority"] is False
    receipt = material["p01_approval_payload"]
    assert receipt["format"] == "claw-android-saf-txt-read-approval.v1"
    assert receipt["exact_tool_arguments"]["path_relative"] == "notes/report.txt"
    assert receipt["exact_tool_arguments"]["content_bytes"] == 0
    assert receipt["approval_decision"]["authority_ref"] == "claw_connector_android_txt_request_v1"
    assert receipt["exact_tool_arguments"]["request_fingerprint"] == (
        receipt["approval_pause"]["invocation_sha256"]
    )

    correlation = asyncio.run(env.history.get_local_task_correlation(env.owner, RUN))
    assert correlation["command_id"] == command["command_id"]
    assert correlation["revision_ref"] == "revision.android.1"


def test_undeclared_withdrawn_or_foreign_scope_is_refused(patch_owner_session, tmp_path):
    env = make_env(tmp_path)
    response = call(env, "POST", routes.CONNECTOR_ANDROID_READ_REQUEST_PATH,
                    body=read_body(root_ref="safroot-foreign"))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "android_read_folder_not_allowed"

    env = make_env(tmp_path / "empty", source=FakeBrokerSource(profile={**PROFILE, "folders": []}))
    response = call(env, "POST", routes.CONNECTOR_ANDROID_READ_REQUEST_PATH, body=read_body())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "android_read_folder_selection_required"

    withdrawn = _consent(withdrawn_at=datetime.now(timezone.utc).isoformat())
    env = make_env(tmp_path / "withdrawn", identity=FakeIdentity(withdrawn))
    assert call(env, "POST", routes.CONNECTOR_ANDROID_READ_REQUEST_PATH,
                body=read_body()).status_code == 403

    other_workspace = _consent(workspace_ref="connector-ws-other")
    env = make_env(tmp_path / "realm", identity=FakeIdentity(other_workspace))
    assert call(env, "POST", routes.CONNECTOR_ANDROID_READ_REQUEST_PATH,
                body=read_body()).status_code == 403


def test_unbound_device_and_missing_profile_keep_distinct_codes(patch_owner_session, tmp_path):
    env = make_env(tmp_path, source=FakeBrokerSource(device=None, profile=PROFILE))
    response = call(env, "POST", routes.CONNECTOR_ANDROID_READ_REQUEST_PATH, body=read_body())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "android_read_device_unbound"

    env = make_env(tmp_path / "no-profile", source=FakeBrokerSource(profile=None))
    response = call(env, "POST", routes.CONNECTOR_ANDROID_READ_REQUEST_PATH, body=read_body())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "android_read_profile_required"


def test_malformed_wire_traversal_and_non_txt_are_refused(patch_owner_session, tmp_path):
    env = make_env(tmp_path)
    for body in (
        read_body(confirmed=False),
        read_body(device_id=""),
        {**read_body(), "account_ref": ACCOUNT},
    ):
        assert call(env, "POST", routes.CONNECTOR_ANDROID_READ_REQUEST_PATH,
                    body=body).status_code == 400
    for path in ("../escape.txt", "/absolute.txt", "notes/report.pdf",
                 "content://documents/report.txt", "notes//report.txt",
                 "file:report.txt"):
        response = call(env, "POST", routes.CONNECTOR_ANDROID_READ_REQUEST_PATH,
                        body=read_body(path_relative=path))
        assert response.status_code == 400, path
    assert env.source.enqueues == []


def test_run_owned_by_another_user_or_workspace_is_not_reachable(patch_owner_session, tmp_path):
    env = make_env(tmp_path)
    response = call(env, "POST", routes.CONNECTOR_ANDROID_READ_REQUEST_PATH,
                    body=read_body(), user=env.other)
    assert response.status_code == 404
    assert env.source.enqueues == []


def test_second_request_for_the_same_run_is_a_conflict_not_a_second_result(
    patch_owner_session, tmp_path, monkeypatch,
):
    env = make_env(tmp_path)

    async def already_bound(**kwargs):
        del kwargs
        raise HistoryError("run already bound")

    monkeypatch.setattr(env.history, "record_local_task_correlation", already_bound)
    response = call(env, "POST", routes.CONNECTOR_ANDROID_READ_REQUEST_PATH,
                    body=read_body())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "android_read_run_already_bound"


def test_unconfigured_source_fails_closed(patch_owner_session, tmp_path):
    env = make_env(tmp_path)
    env.app.state.connector_txt_read_source = SimpleNamespace(configured=False)
    response = call(env, "GET", routes.CONNECTOR_ANDROID_FOLDERS_PATH,
                    params={"device_id": DEVICE})
    assert response.status_code == 503


class _DirectoryBinding:
    def __init__(self, facts, profiles=None, *, fail_profiles=False):
        self.facts = facts
        self.profiles = profiles or []
        self.fail_profiles = fail_profiles
        self.profile_calls = []

    async def device_directory(self, payload):
        del payload
        return {
            "ok": True, "available": True, "owner_scoped": True,
            "device_count": len(self.facts), "devices": self.facts,
        }

    async def android_saf_profiles(self, payload):
        self.profile_calls.append(dict(payload))
        if self.fail_profiles:
            raise RuntimeError("profile read unavailable")
        return self.profiles


def _fact(device, *, account, workspace, state="paired_offline"):
    now = datetime.now(timezone.utc)
    return {
        "canonical_state": state,
        "binding": {
            "binding_ref": "bind_" + device, "device_id": device,
            "account_ref": account, "workspace_ref": workspace,
            "credential_generation": 1,
            "issued_at": (now - timedelta(days=1)).isoformat(),
            "credential_expires_at": (now + timedelta(days=30)).isoformat(),
        },
        "session": None, "heartbeat_last_seen_at": None,
    }


def _directory_env(tmp_path, facts, *, profiles=(), fail_profiles=False):
    history = D1HistoryStore(_open_database(tmp_path / "chat.sqlite3"))
    owner = _accounts(history)[OWNER_SUBJECT]
    workspace = "owner:" + owner
    binding = _DirectoryBinding(
        facts(owner, workspace), profiles=profiles, fail_profiles=fail_profiles,
    )
    settings = Settings.from_values(
        runtime_mode="mock", auth_mode="password", public_base_url=BASE,
        session_secret="5080-directory-test-not-real-session-secret",
        session_max_age_seconds=3600,
    )
    app = create_app(
        settings, history_store=history,
        claw_device_directory_source=BrokerDeviceDirectorySource(binding),
    )
    return SimpleNamespace(
        app=app, settings=settings, owner=owner, workspace=workspace,
        binding=binding,
    )


def _get_directory(env):
    async def perform():
        transport = httpx.ASGITransport(app=env.app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE) as client:
            client.cookies.set(SESSION_COOKIE, create_session_token(env.settings, env.owner))
            return await client.get(CLAW_DEVICE_DIRECTORY_PATH)
    return asyncio.run(perform())


def test_directory_labels_the_phone_without_changing_pc_rows(tmp_path):
    env = _directory_env(
        tmp_path,
        lambda owner, workspace: [
            _fact("pc-home", account=owner, workspace=workspace),
            _fact("phone-1", account=owner, workspace=workspace),
        ],
        profiles=[{
            "binding_ref": "bind_phone-1", "device_id": "phone-1",
            "platform": "android",
            "capabilities": ["local.filesystem.read"],
            "read_suffix": ".txt", "folder_count": 2,
        }],
    )
    response = _get_directory(env)
    assert response.status_code == 200
    rows = {row["deviceId"]: row for row in response.json()["devices"]}
    assert rows["pc-home"] == {
        "deviceId": "pc-home", "deviceName": None, "platform": None,
        "state": "OFFLINE", "usable": False, "revoked": False, "expired": False,
    }
    assert rows["phone-1"] == {
        "deviceId": "phone-1", "deviceName": None, "platform": "android",
        "state": "OFFLINE", "usable": False, "revoked": False, "expired": False,
        "capabilities": ["local.filesystem.read"], "readSuffix": ".txt",
        "folderCount": 2,
    }
    assert env.binding.profile_calls == [{
        "account_ref": env.owner, "workspace_ref": env.workspace,
    }]
    assert "safroot" not in response.text
    assert "NEVER_RENDER_ME" not in response.text


def test_directory_enrichment_failure_never_denies_pc_rows(tmp_path):
    env = _directory_env(
        tmp_path,
        lambda owner, workspace: [
            _fact("pc-home", account=owner, workspace=workspace),
        ],
        fail_profiles=True,
    )
    response = _get_directory(env)
    assert response.status_code == 200
    assert response.json()["devices"][0]["deviceId"] == "pc-home"
    assert response.json()["devices"][0]["platform"] is None


def test_directory_ignores_a_profile_that_does_not_match_the_canonical_binding(tmp_path):
    env = _directory_env(
        tmp_path,
        lambda owner, workspace: [
            _fact("phone-1", account=owner, workspace=workspace),
        ],
        profiles=[{
            "binding_ref": "bind_other", "device_id": "phone-1",
            "platform": "android",
            "capabilities": ["local.filesystem.read"],
            "read_suffix": ".txt", "folder_count": 2,
        }],
    )
    response = _get_directory(env)
    assert response.status_code == 200
    assert response.json()["devices"][0]["platform"] is None
