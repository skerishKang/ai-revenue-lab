"""COM2 signs the actual Google state ingress, not a permissive HTTP double.

The prior client and ingress tests exercised opposite halves with canned
responses or hand-built v1 proofs. This joins the real v2 client, Worker
dispatcher, DO replay store and bounded Google truth on in-memory SQLite.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.connector_workspace_truth import CloudflareGoogleOAuthWorkspaceTruth
from app.local_service_bridge import HttpRpcBinding, ServiceRpcHttpError

CP_ROOT = Path(__file__).resolve().parents[3] / "packages" / "padiem-control-plane"
SECRET = "synthetic-google-ingress-secret-7089"
WORKSPACE = "workspace.com2.integration"


def _load_file(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_com2_v2_client_reaches_only_bounded_google_truth(monkeypatch):
    # Reuse existing SQLite and Worker-surface doubles. Load them by path to
    # avoid ambiguous test-module imports when both product suites run together.
    storage_helpers = _load_file(
        "_com2_google_storage_helpers",
        CP_ROOT / "tests" / "test_google_oauth_durable_store.py",
    )
    ingress_helpers = _load_file(
        "_com2_google_ingress_helpers",
        CP_ROOT / "tests" / "test_internal_rpc_ingress.py",
    )
    # Scope the runtime substitution to this load. Never leave a fake workers
    # module installed for another test collected in the full Chat suite.
    with monkeypatch.context() as runtime_patch:
        runtime = types.ModuleType("workers")
        runtime.DurableObject = ingress_helpers._FakeDurableObject
        runtime.WorkerEntrypoint = ingress_helpers._FakeWorkerEntrypoint
        runtime.Response = ingress_helpers._FakeResponse
        runtime_patch.setitem(sys.modules, "workers", runtime)
        worker = _load_file("_com2_google_worker", CP_ROOT / "google_oauth_worker.py")

    from google_oauth_durable_store import (
        DurableGoogleOAuthCredential,
        GOOGLE_CALENDAR_READONLY_SCOPE,
    )

    storage = storage_helpers.FakeDurableStorage()
    # Compose the real read/replay ports without creating OAuth exchange or
    # credential-unsealing ports. This scenario must never need either port.
    durable = object.__new__(worker.GoogleOAuthDurableObject)
    durable._store = worker.CloudflareDurableGoogleOAuthStore(storage)
    durable._service_ids = worker.SqliteServiceIdReplayStore(storage)
    durable._store.save_credential(
        DurableGoogleOAuthCredential(
            binding_ref="binding.calendar.com2",
            connector_id="google-calendar",
            actor_ref="actor.calendar.com2",
            account_ref="account.calendar.com2",
            workspace_ref=WORKSPACE,
            scopes=(GOOGLE_CALENDAR_READONLY_SCOPE,),
            sealed_refresh_token="sealed:v1:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
            issued_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            # #7248: Calendar bindings always carry the verified Google account
            # subject (reconnect replacement is account-scoped).
            provider_subject="google-sub-calendar-owner",
            expires_at=None,
        )
    )
    before = storage.connection.execute(
        "SELECT * FROM google_oauth_refresh_credential"
    ).fetchall()
    env = types.SimpleNamespace(
        GOOGLE_OAUTH_STATE=ingress_helpers._Namespace(durable),
        PADIEM_GOOGLE_STATE_RPC_INGRESS_SECRET=SECRET,
        PADIEM_RPC_SERVICE_ID_POLICY="required",
    )
    gateway = worker.Default(env=env)
    requests = []
    responses = []

    async def send_to_worker(request: httpx.Request) -> httpx.Response:
        wire = ingress_helpers._Request(
            str(request.url),
            method=request.method,
            headers=dict(request.headers),
            body=request.content,
        )
        result = await gateway.fetch(wire)
        requests.append(wire)
        responses.append(result)
        return httpx.Response(
            result.status, content=result.body, headers=result.headers
        )

    try:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(send_to_worker), follow_redirects=False
        ) as http:
            binding = HttpRpcBinding(
                "https://google-state.example.test", SECRET, client=http
            )
            truth = CloudflareGoogleOAuthWorkspaceTruth(binding)
            default = await truth.workspace_connector_state(workspace_ref=WORKSPACE)
            calendar = await truth.workspace_calendar_connector_state(
                workspace_ref=WORKSPACE
            )

            assert {row["connector_id"] for row in default} == {"gmail", "google-drive"}
            assert all(row["state"] == "not_connected" for row in default)
            assert calendar == ({
                "connector_id": "google-calendar",
                "state": "connected",
                "usable": True,
                "expires_present": False,
                "ambiguous": False,
            },)
            assert all(set(row) == {
                "connector_id", "state", "usable", "expires_present", "ambiguous"
            } for row in default + calendar)
            assert [str(request.url).rsplit("/", 1)[-1] for request in requests] == [
                "workspace_connector_state", "workspace_calendar_connector_state"
            ]
            assert all(
                request.headers["x-padiem-service-proof"].startswith("v2=")
                for request in requests
            )
            ids = {request.headers["x-padiem-service-id"] for request in requests}
            assert len(ids) == 2
            assert storage.scalar("SELECT COUNT(*) FROM service_request_ids") == 2

            # Replay the captured bytes directly: no client retry may replace
            # the id and hide a failed replay boundary.
            replay = await gateway.fetch(requests[0])
            assert replay.status == 409
            assert json.loads(replay.body)["error"]["code"] == "rpc_replay_detected"

            # This is the old #7089 composition: a v1/no-id client must not
            # silently appear compatible with a target enforcing signed ids.
            legacy = HttpRpcBinding(
                "https://google-state.example.test", SECRET,
                client=http, sign_request_id=False,
            )
            with pytest.raises(ServiceRpcHttpError):
                await legacy.workspace_connector_state({"workspace_ref": WORKSPACE})
            assert responses[-1].status == 403
            assert json.loads(responses[-1].body)["error"]["code"] == "rpc_service_id_required"

            # Binding selection is a reviewed private ingress method (#7245, the
            # P01 prerequisite). A correctly signed caller gets the bounded
            # selection projection and never a credential, scope or sealed token.
            selection = await binding.select_calendar_binding({"workspace_ref": WORKSPACE})
            assert selection["ok"] is True
            assert selection["selection"] == {
                "status": "resolved",
                "connector_id": "google-calendar",
                "workspace_ref": WORKSPACE,
                "binding_ref": "binding.calendar.com2",
                "actor_ref": "actor.calendar.com2",
            }
            assert "provider_subject" not in selection["selection"]
            for forbidden in ("sealed_refresh_token", "scopes", "access_token"):
                assert forbidden not in json.dumps(selection)

            # A valid signature cannot turn the read into a caller-selected
            # connector projection.
            rejected = await binding.workspace_connector_state({
                "workspace_ref": WORKSPACE, "connector_ids": ["google-calendar"],
            })
            assert rejected["ok"] is False
            assert rejected["error"]["code"] == "invalid_google_oauth_ingress"

        assert storage.connection.execute(
            "SELECT * FROM google_oauth_refresh_credential"
        ).fetchall() == before
    finally:
        storage.connection.close()
