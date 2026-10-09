"""#3650 — the local/nonprod connect initiating leg, fail-closed by default.

The route must mint exactly one canonical pairing challenge for the composed
TEST principal, refuse every other composition, and format the mint output into
the existing ``#3095`` deep-link schema. Production keeps the unconfigured
default, so the deployed surface is a bounded refusal with no minting path.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import httpx
import pytest

from app.app_factory import create_app
from app.auth import SESSION_COOKIE, create_session_token
from app.claw_local_connect_composition import (
    NonprodBrokerPairingConnectPort,
    build_nonprod_claw_local_connect_port,
)
from app.claw_local_connect_routes import CLAW_LOCAL_CONNECT_PATH
from app.config import Settings

# Session identity is the chat profile id (``usr_*``); the canonical account
# the challenge is minted for is the TEST principal the host was started with.
# Mapping the former to the latter is exactly what the composition owns.
OWNER = "usr_3650_owner"
OTHER = "usr_3650_other"
ACCOUNT = "owner-3650@example.test"
WORKSPACE = "workspace.3650.e2e"
BASE_ORIGIN = "https://chat.example.test"
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)


class FakeMintPort:
    """A canonical-shaped mint double: canned response, call counting."""

    configured = True

    def __init__(self, *, result=None, allowed_owner_ids=(OWNER,), raise_error=False):
        self.result = result
        self.raise_error = raise_error
        self.allowed_owner_ids = frozenset(allowed_owner_ids)
        self.calls: list[dict] = []

    def issue_pairing_challenge(self, *, owner_id, conversation_id, now):
        self.calls.append(
            {"owner_id": owner_id, "conversation_id": conversation_id, "now": now}
        )
        if self.raise_error:
            raise RuntimeError("upstream exploded")
        return self.result


def _canonical_mint() -> dict:
    return {
        "ok": True,
        "challenge": {
            "challenge_id": "challenge.3650.abcdef0123456789",
            "account_ref": ACCOUNT,
            "workspace_ref": WORKSPACE,
            "issued_at": NOW.isoformat(),
            "expires_at": "2026-10-08T09:05:00+00:00",
            "ttl_seconds": 300,
        },
        "pairing_code": "a" * 32,
        "pairing_code_returned_once": True,
        "proof_transcript": "padiem-broker-pairing-proof-v1",
    }


class _AuthReadyStore:
    """Minimal store: auth_ready() needs a non-None store (see #3476 tests)."""

    async def get_user(self, user_id: str):
        return None

    async def list_projects(self, user_id: str):
        return []


def _app(port=None):
    settings = Settings(
        session_secret="3650-connect-test-secret",
        auth_mode="mock",
        public_base_url=BASE_ORIGIN,
    )
    return create_app(settings, history_store=_AuthReadyStore(), claw_local_connect_port=port), settings


def _run(coro):
    import asyncio

    return asyncio.run(coro)


def _request(app, settings, *, method: str, owner: str | None, origin: str | None, body: dict | None = None):
    """One ASGI request with the harness's cookie/session shape."""

    import asyncio

    headers = {}
    if origin is not None:
        headers["Origin"] = origin
    if owner is not None:
        token = create_session_token(settings, owner)
        headers["Cookie"] = f"{SESSION_COOKIE}={token}"

    async def drive():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url=BASE_ORIGIN) as client:
            if method == "GET":
                return await client.get(CLAW_LOCAL_CONNECT_PATH, headers=headers)
            return await client.post(
                CLAW_LOCAL_CONNECT_PATH,
                json=body if body is not None else {},
                headers=headers,
            )

    return asyncio.run(drive())


def _get(app, settings, owner: str | None = OWNER):
    return _request(app, settings, method="GET", owner=owner, origin=None)


def _post_as(app, settings, owner: str | None = OWNER, body: dict | None = None, origin: str | None = BASE_ORIGIN):
    return _request(app, settings, method="POST", owner=owner, origin=origin, body=body)


def _client(app, settings, owner: str | None = OWNER):
    """Context-manager facade kept for the earlier tests."""

    class _SyncFacade:
        def __init__(self):
            self._responses = []

        def get(self, path, **kwargs):
            assert path == CLAW_LOCAL_CONNECT_PATH
            return _get(app, settings, owner=owner)

        def post(self, path, **kwargs):
            assert path == CLAW_LOCAL_CONNECT_PATH
            return _post_as(app, settings, owner=owner, body=kwargs.get("json", {}))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    return _SyncFacade()


def _post(client, body: dict | None = None):
    return client.post(
        CLAW_LOCAL_CONNECT_PATH,
        json=body if body is not None else {},
    )


def test_default_composition_refuses_the_initiating_leg():
    app, settings = _app(None)
    with _client(app, settings, owner=None) as client:
        response = _post(client)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "local_connect_unconfigured"
    assert response.headers["Cache-Control"] == "no-store, max-age=0"

    with _client(app, settings, owner=None) as client:
        probe = client.get(CLAW_LOCAL_CONNECT_PATH)
    assert probe.status_code == 401  # no session, no availability answer


def test_status_probe_is_invisible_until_a_port_is_composed():
    app, settings = _app(None)
    with _client(app, settings) as client:
        probe = client.get(CLAW_LOCAL_CONNECT_PATH)
    assert probe.status_code == 200
    assert probe.json()["ok"] is True
    assert probe.json()["available"] is False

    port = FakeMintPort(result=_canonical_mint())
    app2, settings2 = _app(port)
    with _client(app2, settings2) as client:
        probe2 = client.get(CLAW_LOCAL_CONNECT_PATH)
    assert probe2.json()["available"] is True


def test_connect_requires_a_session():
    port = FakeMintPort(result=_canonical_mint())
    app, settings = _app(port)
    with _client(app, settings, owner=None) as client:
        response = _post(client)
    assert response.status_code == 401
    assert port.calls == []


def test_connect_mints_once_and_returns_the_existing_deep_link_schema():
    port = FakeMintPort(result=_canonical_mint())
    app, settings = _app(port)
    with _client(app, settings) as client:
        response = _post(client, {"conversationId": "conv-3650"})

    assert response.status_code == 200
    assert len(port.calls) == 1  # ONE canonical mint per user action
    assert port.calls[0]["owner_id"] == OWNER
    handoff = response.json()["handoff"]
    assert handoff["kind"] == "deep_link"
    assert handoff["conversationId"] == "conv-3650"
    assert re.fullmatch(
        r"padiem://pair\?code=[0-9a-f]{32}&challenge=[A-Za-z0-9._:@+%-]+",
        handoff["value"],
    ), handoff["value"]
    assert len(handoff["value"]) <= 512


def test_connect_refuses_a_session_owner_outside_the_allowlist():
    port = FakeMintPort(result=_canonical_mint())
    app, settings = _app(port)
    with _client(app, settings, owner=OTHER) as client:
        response = _post(client, {"conversationId": "conv-3650"})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "local_connect_owner_unauthorized"
    assert port.calls == []  # the mint never fires for a foreign session


def test_connect_reports_a_canonical_refusal_bounded_without_retry():
    port = FakeMintPort(result=None)
    app, settings = _app(port)
    with _client(app, settings) as client:
        response = _post(client, {})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "local_connect_refused"
    assert len(port.calls) == 1  # refused once; no retry, no second mint


def test_connect_reports_an_exceptioning_port_bounded():
    port = FakeMintPort(raise_error=True)
    app, settings = _app(port)
    with _client(app, settings) as client:
        response = _post(client, {})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "local_connect_refused"
    # No exception text escaped into the response body.
    assert "exploded" not in response.text


def test_connect_drops_an_out_of_schema_mint():
    port = FakeMintPort(result={"ok": True, "pairing_code": "zz", "challenge": {"challenge_id": "x"}})
    app, settings = _app(port)
    with _client(app, settings) as client:
        response = _post(client, {})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "local_connect_invalid_mint"


def test_connect_rejects_a_malformed_conversation_id():
    port = FakeMintPort(result=_canonical_mint())
    app, settings = _app(port)
    with _client(app, settings) as client:
        response = _post(client, {"conversationId": "bad id with spaces"})
    assert response.status_code == 400
    assert port.calls == []


def test_connect_is_covered_by_the_same_origin_guard():
    port = FakeMintPort(result=_canonical_mint())
    app, settings = _app(port)
    response = _post_as(app, settings, owner=OWNER, body={}, origin="https://evil.example.test")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_rejected"
    assert port.calls == []


def test_port_construction_requires_loopback_and_owners():
    with pytest.raises(ValueError):
        NonprodBrokerPairingConnectPort(
            broker_base_url="https://broker.example.test",
            account_ref=OWNER,
            workspace_ref="workspace.3650.e2e",
            allowed_owner_ids=(OWNER,),
        )
    with pytest.raises(ValueError):
        NonprodBrokerPairingConnectPort(
            broker_base_url="http://127.0.0.1:43117",
            account_ref=OWNER,
            workspace_ref="workspace.3650.e2e",
            allowed_owner_ids=(),
        )
    assert build_nonprod_claw_local_connect_port(
        broker_base_url="http://127.0.0.1:43117",
        account_ref=OWNER,
        workspace_ref="workspace.3650.e2e",
        allowed_owner_ids=(OWNER,),
    ) is not None
    assert build_nonprod_claw_local_connect_port(
        broker_base_url="http://10.1.2.3:43117",
        account_ref=OWNER,
        workspace_ref="workspace.3650.e2e",
        allowed_owner_ids=(OWNER,),
    ) is None


def test_missing_allowlist_fails_closed_and_status_is_not_leaked():
    port = FakeMintPort(result=_canonical_mint())
    del port.allowed_owner_ids  # miscomposed port cannot authorize anybody
    app, settings = _app(port)
    with _client(app, settings) as client:
        response = _post(client)
        probe = client.get(CLAW_LOCAL_CONNECT_PATH)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "local_connect_owner_unauthorized"
    assert probe.status_code == 200
    assert probe.json()["available"] is False
    assert port.calls == []


def test_foreign_owner_status_probe_does_not_advertise_pairing():
    port = FakeMintPort(result=_canonical_mint())
    app, settings = _app(port)
    with _client(app, settings, owner=OTHER) as client:
        probe = client.get(CLAW_LOCAL_CONNECT_PATH)
    assert probe.status_code == 200
    assert probe.json()["available"] is False


def test_direct_composition_rejects_wrong_owner_before_network():
    port = NonprodBrokerPairingConnectPort(
        broker_base_url="http://127.0.0.1:43117",
        account_ref=ACCOUNT,
        workspace_ref=WORKSPACE,
        allowed_owner_ids=(OWNER,),
    )
    assert port.issue_pairing_challenge(
        owner_id=OTHER, conversation_id=None, now=NOW,
    ) is None


def test_nonprod_connect_port_refuses_cross_workspace_mint():
    import json
    from unittest.mock import patch

    port = NonprodBrokerPairingConnectPort(
        broker_base_url="http://127.0.0.1:43117",
        account_ref=ACCOUNT,
        workspace_ref=WORKSPACE,
        allowed_owner_ids=(OWNER,),
    )
    forged = _canonical_mint()
    forged["challenge"] = {**forged["challenge"], "workspace_ref": "foreign_workspace"}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self, count):
            assert count > 0
            return json.dumps(forged).encode("utf-8")

    class Opener:
        def open(self, request, timeout):
            return Response()

    with patch(
        "app.claw_local_connect_composition.urllib.request.build_opener",
        return_value=Opener(),
    ) as stub:
        assert port.issue_pairing_challenge(
            owner_id=OWNER, conversation_id="conv-3650", now=NOW,
        ) is None
    stub.assert_called_once()
    from app.claw_local_connect_composition import _NoRedirect
    assert isinstance(stub.call_args.args[0], _NoRedirect)


def test_nonprod_port_never_follows_broker_redirects():
    import urllib.error
    from unittest.mock import patch
    from app.claw_local_connect_composition import _NoRedirect

    assert _NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://elsewhere.invalid") is None
    port = NonprodBrokerPairingConnectPort(
        broker_base_url="http://127.0.0.1:43117",
        account_ref=ACCOUNT, workspace_ref=WORKSPACE,
        allowed_owner_ids=(OWNER,),
    )

    class RedirectingOpener:
        def open(self, *_args, **_kwargs):
            raise urllib.error.HTTPError(
                "http://127.0.0.1:43117/v1/broker/pairings/challenge",
                302, "unexpected redirect", {}, None,
            )

    with patch(
        "app.claw_local_connect_composition.urllib.request.build_opener",
        return_value=RedirectingOpener(),
    ) as stub:
        assert port.issue_pairing_challenge(
            owner_id=OWNER, conversation_id=None, now=NOW,
        ) is None
    stub.assert_called_once()


def test_contract_markers_hold():
    from app import claw_local_connect_routes as routes
    from app import claw_local_connect_composition as composition

    assert routes.NONPROD_EVIDENCE_HOST_ONLY is True
    assert routes.PRODUCTION_PAIRING_STORE_ADDED is False
    assert routes.REQUEST_BODY_IS_AUTHORITY is False
    assert routes.SCOPE_MISMATCH_BYPASS is False
    assert routes.PRODUCTION_MUTATION is False
    assert composition.NONPROD_EVIDENCE_HOST_ONLY is True
    assert composition.LOOPBACK_ONLY is True
    assert composition.CANONICAL_MINT_REUSED_NOT_REIMPLEMENTED is True
    assert composition.PRODUCTION_MUTATION is False
