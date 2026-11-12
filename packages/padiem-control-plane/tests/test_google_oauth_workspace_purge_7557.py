"""#7557: account deletion revokes and deletes every Google credential of a workspace.

Before this change a disconnect only stamped ``revoked_at`` and kept the sealed
refresh token, and nothing asked Google to drop the grant. These tests run the
real production store (rows proven by read-back, ``rowsWritten`` always 0) with
a fake sealer and a fake Google revoke endpoint — no network.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs
import sys

import pytest

from google_oauth_durable_store import (
    B66_GOOGLE_DRIVE_FULL_CONNECTOR,
    B66_GOOGLE_DRIVE_OIDC_SCOPES,
    GMAIL_READONLY_SCOPE,
    GOOGLE_DRIVE_FULL_SCOPE,
    GOOGLE_DRIVE_READONLY_SCOPE,
    DurableGoogleOAuthCredential,
)
from google_oauth_persisted_store import CloudflareDurableGoogleOAuthStore
from google_oauth_workspace_purge import (
    ALREADY_INVALID,
    GOOGLE_REVOKE_URL,
    REVOKED,
    CloudflareGoogleOAuthRevokePort,
    GoogleOAuthWorkspacePurgeRuntime,
)
from padiem_control_plane.contracts import ControlPlaneContractError
from test_google_oauth_persisted_store import AlwaysZeroRowsWrittenStorage

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)
MINE = "workspace.mine.1"
OTHER = "workspace.other.1"


def _sealed(name: str) -> str:
    return "sealed:v1:" + (name.replace(".", "x").replace("-", "y") + "A" * 32)[:40]


def _credential(binding: str, workspace: str, connector: str = "google-drive") -> DurableGoogleOAuthCredential:
    extra: dict = {}
    if connector == "google-drive":
        scopes = (GOOGLE_DRIVE_READONLY_SCOPE,)
    elif connector == "gmail":
        scopes = (GMAIL_READONLY_SCOPE,)
    else:
        scopes = (GOOGLE_DRIVE_FULL_SCOPE,) + B66_GOOGLE_DRIVE_OIDC_SCOPES
        extra = {"provider_subject": "google-sub-12345678", "provider_email": "owner@drive.test"}
    return DurableGoogleOAuthCredential(
        binding_ref=binding, connector_id=connector, actor_ref="actor.1",
        account_ref="account.1", workspace_ref=workspace, scopes=scopes,
        sealed_refresh_token=_sealed(binding), issued_at=NOW - timedelta(days=1), **extra,
    )


def _store():
    storage = AlwaysZeroRowsWrittenStorage()
    store = CloudflareDurableGoogleOAuthStore(storage)
    store.save_credential(_credential("bind.drive", MINE))
    store.save_credential(_credential("bind.gmail", MINE, "gmail"))
    store.save_credential(_credential("bind.b66", MINE, B66_GOOGLE_DRIVE_FULL_CONNECTOR))
    store.save_credential(_credential("bind.stranger", OTHER, "gmail"))
    # An earlier disconnect left a revoked row with its sealed token behind.
    store.revoke_credential(binding_ref="bind.gmail", revoked_at=NOW - timedelta(hours=1))
    return store, storage


def _count(storage, table: str, workspace: str | None = None) -> int:
    if table == "google_oauth_provider_destination":
        return storage.scalar(
            "SELECT COUNT(*) FROM google_oauth_provider_destination d WHERE NOT EXISTS ("
            "SELECT 1 FROM google_oauth_refresh_credential c WHERE c.binding_ref = d.binding_ref "
            "AND c.workspace_ref <> ?)", workspace or "")
    return storage.scalar(
        f"SELECT COUNT(*) FROM {table} WHERE workspace_ref = ?", workspace)


class FakeSealer:
    def __init__(self, broken: set[str] = frozenset()):
        self.broken = broken

    async def unseal_text(self, *, envelope: str, context):
        if context.record_ref in self.broken:
            raise ControlPlaneContractError("invalid_sealed_blob", "cannot unseal")
        return "refresh-" + context.record_ref


class FakeRevoke:
    """Google's revoke endpoint: answers per token; ``fail`` tokens fail once each."""

    def __init__(self, *, fail: dict[str, int] | None = None, invalid: set[str] = frozenset()):
        self.calls: list[str] = []
        self.fail = dict(fail or {})
        self.invalid = invalid

    async def revoke_token(self, *, token: str) -> str:
        self.calls.append(token)
        if self.fail.get(token, 0) > 0:
            self.fail[token] -= 1
            raise ControlPlaneContractError("google_oauth_revoke_failed", "down")
        return ALREADY_INVALID if token in self.invalid else REVOKED


def _runtime(store, sealer=None, revoke=None):
    return GoogleOAuthWorkspacePurgeRuntime(
        store=store, sealer=sealer or FakeSealer(), revoke_port=revoke or FakeRevoke(),
        clock=lambda: NOW,
    )


def test_every_credential_of_the_workspace_is_revoked_at_google_and_deleted():
    store, storage = _store()
    revoke = FakeRevoke()
    result = asyncio.run(_runtime(store, revoke=revoke).purge(workspace_ref=MINE))
    assert result == {"purged": 3, "remaining": 0, "provider_revoke_skipped": 0}
    # The already-disconnected Gmail row is revoked at Google too.
    assert sorted(revoke.calls) == ["refresh-bind.b66", "refresh-bind.drive", "refresh-bind.gmail"]
    assert _count(storage, "google_oauth_refresh_credential", MINE) == 0
    assert storage.scalar(
        "SELECT COUNT(*) FROM google_oauth_provider_destination WHERE binding_ref = 'bind.b66'") == 0
    # Another workspace is untouched and still usable.
    assert _count(storage, "google_oauth_refresh_credential", OTHER) == 1
    assert storage.scalar(
        "SELECT revoked_at FROM google_oauth_refresh_credential WHERE binding_ref='bind.stranger'") is None


def test_a_failed_google_revoke_leaves_an_unusable_row_and_the_next_call_finishes():
    store, storage = _store()
    revoke = FakeRevoke(fail={"refresh-bind.drive": 1})
    first = asyncio.run(_runtime(store, revoke=revoke).purge(workspace_ref=MINE))
    assert first == {"purged": 2, "remaining": 1, "provider_revoke_skipped": 0}
    # The row that stays can no longer issue an access lease.
    assert storage.scalar(
        "SELECT COUNT(*) FROM google_oauth_refresh_credential "
        "WHERE workspace_ref = ? AND revoked_at IS NULL", MINE) == 0
    second = asyncio.run(_runtime(store, revoke=revoke).purge(workspace_ref=MINE))
    assert second == {"purged": 1, "remaining": 0, "provider_revoke_skipped": 0}
    assert revoke.calls.count("refresh-bind.drive") == 2
    assert revoke.calls.count("refresh-bind.gmail") == 1  # finished rows are not revisited
    assert _count(storage, "google_oauth_refresh_credential", MINE) == 0
    third = asyncio.run(_runtime(store, revoke=revoke).purge(workspace_ref=MINE))
    assert third == {"purged": 0, "remaining": 0, "provider_revoke_skipped": 0}


def test_an_envelope_that_cannot_be_unsealed_is_deleted_and_counted_not_retried_forever():
    store, storage = _store()
    revoke = FakeRevoke()
    result = asyncio.run(
        _runtime(store, sealer=FakeSealer(broken={"bind.drive"}), revoke=revoke).purge(workspace_ref=MINE))
    assert result == {"purged": 2, "remaining": 0, "provider_revoke_skipped": 1}
    assert "refresh-bind.drive" not in revoke.calls
    assert _count(storage, "google_oauth_refresh_credential", MINE) == 0


def test_a_token_google_already_dropped_counts_as_revoked():
    store, storage = _store()
    revoke = FakeRevoke(invalid={"refresh-bind.gmail"})
    result = asyncio.run(_runtime(store, revoke=revoke).purge(workspace_ref=MINE))
    assert result["remaining"] == 0 and result["purged"] == 3


class _Response:
    def __init__(self, status: int, text: str = ""):
        self.status = status
        self._text = text

    async def text(self):
        return self._text


@pytest.mark.parametrize("status, body, expected", [
    (200, "", REVOKED),
    (400, '{"error": "invalid_token", "error_description": "Token expired or revoked"}', ALREADY_INVALID),
])
def test_the_revoke_port_posts_the_token_to_google_and_reads_the_answer(monkeypatch, status, body, expected):
    sent = []

    async def fetch(url, *, method, headers, body):
        sent.append((url, method, headers, body))
        return _Response(status, body_text)

    body_text = body
    monkeypatch.setitem(sys.modules, "workers", SimpleNamespace(fetch=fetch))
    outcome = asyncio.run(CloudflareGoogleOAuthRevokePort().revoke_token(token="refresh/secret+1"))
    assert outcome == expected
    [(url, method, headers, form)] = sent
    assert url == GOOGLE_REVOKE_URL == "https://oauth2.googleapis.com/revoke"
    assert method == "POST"
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert parse_qs(form) == {"token": ["refresh/secret+1"]}


@pytest.mark.parametrize("status, body", [
    (400, '{"error": "invalid_request"}'), (500, ""), (503, "down"), (429, ""),
])
def test_any_other_google_answer_is_a_retryable_failure(monkeypatch, status, body):
    async def fetch_ok(url, **kwargs):
        return _Response(status, body)

    monkeypatch.setitem(sys.modules, "workers", SimpleNamespace(fetch=fetch_ok))
    with pytest.raises(ControlPlaneContractError) as info:
        asyncio.run(CloudflareGoogleOAuthRevokePort().revoke_token(token="t"))
    assert info.value.code == "google_oauth_revoke_failed"


def test_a_network_failure_is_a_retryable_failure(monkeypatch):
    async def fetch(url, **kwargs):
        raise OSError("unreachable")

    monkeypatch.setitem(sys.modules, "workers", SimpleNamespace(fetch=fetch))
    with pytest.raises(ControlPlaneContractError):
        asyncio.run(CloudflareGoogleOAuthRevokePort().revoke_token(token="t"))


def _worker_module(monkeypatch):
    import importlib.util
    from pathlib import Path
    import types

    fake = types.ModuleType("workers")

    class _Entrypoint:
        def __init__(self, env=None):
            self.env = env

    class _DurableObject:
        def __init__(self, ctx, env):
            self.ctx, self.env = ctx, env

    fake.Response = object
    fake.WorkerEntrypoint = _Entrypoint
    fake.DurableObject = _DurableObject
    monkeypatch.setitem(sys.modules, "workers", fake)
    path = Path(__file__).parents[1] / "google_oauth_worker.py"
    spec = importlib.util.spec_from_file_location("google_oauth_worker_purge_7557_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_durable_object_rpc_is_closed_to_the_workspace(monkeypatch):
    worker = _worker_module(monkeypatch)
    store, storage = _store()
    instance = worker.GoogleOAuthDurableObject.__new__(worker.GoogleOAuthDurableObject)
    instance._workspace_purge_runtime = _runtime(store)
    refused = asyncio.run(instance.purge_workspace_credentials(
        {"workspace_ref": MINE, "binding_ref": "bind.drive"}))
    assert refused["ok"] is False
    assert _count(storage, "google_oauth_refresh_credential", MINE) == 3
    assert asyncio.run(instance.purge_workspace_credentials({"workspace_ref": MINE})) == {
        "ok": True, "purged": 3, "remaining": 0, "provider_revoke_skipped": 0}
    assert _count(storage, "google_oauth_refresh_credential", OTHER) == 1


def test_the_gateway_forwards_the_purge_to_the_one_authority_object(monkeypatch):
    worker = _worker_module(monkeypatch)
    seen = []

    class _Stub:
        async def purge_workspace_credentials(self, payload):
            seen.append(payload)
            return {"ok": True, "purged": 0, "remaining": 0, "provider_revoke_skipped": 0}

    gateway = worker.Default.__new__(worker.Default)
    gateway._stub = lambda: _Stub()
    answer = asyncio.run(gateway.purge_workspace_credentials({"workspace_ref": MINE}))
    assert answer["ok"] is True and seen == [{"workspace_ref": MINE}]
    assert "purge_workspace_credentials" in worker.Default.RPC_INGRESS_METHODS
