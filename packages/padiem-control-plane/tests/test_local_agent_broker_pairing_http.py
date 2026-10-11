from __future__ import annotations

import base64
from datetime import datetime, timezone
import json

from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_http import (
    DurableLocalAgentSessionRecord,
    TrustedLocalAgentHttpAuthContext,
)
from padiem_control_plane.local_agent_broker_pairing import (
    InMemoryBrokerPairingAuthority,
    pairing_proof_ref,
)
from padiem_control_plane.local_agent_broker_pairing_http import (
    PAIRING_CHALLENGE_ROUTE,
    PAIRING_CHALLENGE_ROUTES,
    PAIRING_CODE_REUSABLE,
    PAIRING_HTTP_BOUNDARY,
    PAIRING_REDEEM_PROOF_VERIFIED_BEFORE_BINDING,
    PAIRING_REDEEM_REQUIRES_DEVICE_CREDENTIAL,
    PAIRING_REDEEM_REQUIRES_TLS_ATTESTATION,
    PAIRING_REDEEM_ROUTE,
    PRODUCTION_PAIRING_ENDPOINT_CONFIGURED,
    PRODUCTION_READY,
    PUBLIC_PAIRING_EDGE_SERVICE_CONFIGURED,
    RAW_DEVICE_CREDENTIAL_LOGGED,
    RAW_PAIRING_CODE_LOGGED,
    SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY,
    PairingAndAdmissionLocalAgentBrokerHttpHandler,
    PairingEnabledLocalAgentBrokerHttpHandler,
)
from padiem_control_plane.local_agent_broker_rpc import LocalAgentBrokerRpcFacade

BASE = datetime(2026, 9, 26, 5, 0, tzinfo=timezone.utc)
BROKER_PEPPER = b"control-plane-local-agent-broker-pepper"
PAIRING_PEPPER = b"control-plane-local-agent-pairing-pepper"
CREDENTIAL = b"http-pairing-redeemed-credential"
ADMISSION_REF = "admission_http_pairing_1"
EVIDENCE_REF = "evidence_http_pairing_1"


class _Clock:
    def __init__(self, now: datetime = BASE) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _DurableState:
    durable = True

    def __init__(self) -> None:
        self.records: dict[str, DurableLocalAgentSessionRecord] = {}

    def save_session(self, record: DurableLocalAgentSessionRecord) -> None:
        self.records[record.session_id] = record

    def load_session(self, session_id: str) -> DurableLocalAgentSessionRecord:
        try:
            return self.records[session_id]
        except KeyError as exc:
            raise RuntimeError("session is not present in durable test state") from exc

    def record_last_seen(self, session_id: str, *, seen_at: datetime) -> DurableLocalAgentSessionRecord:
        record = self.load_session(session_id).with_last_seen(seen_at)
        self.records[session_id] = record
        return record


class _MaterialResolver:
    def resolve(self, request):
        del request
        raise AssertionError("pairing tests never resolve command material")


class _References:
    def __call__(self) -> tuple[str, str]:
        return ADMISSION_REF, EVIDENCE_REF


def _auth(
    *,
    principal_ref: str = "principal.browser.1",
    account_ref: str = "account.1",
    workspace_ref: str = "workspace.1",
    authenticated: bool = True,
    tls_verified: bool = True,
) -> TrustedLocalAgentHttpAuthContext:
    return TrustedLocalAgentHttpAuthContext(
        principal_ref=principal_ref,
        account_ref=account_ref,
        workspace_ref=workspace_ref,
        authenticated=authenticated,
        tls_verified=tls_verified,
    )


def _handler(*, composed: bool = False, nonce_prefix: str = "a"):
    authority = InMemoryLocalAgentBrokerAuthority(pepper=BROKER_PEPPER, authority_ref="control-plane.local-agent-broker.v1")
    counter = {"value": 0}

    def nonce() -> str:
        counter["value"] += 1
        return f"{nonce_prefix}{counter['value']:031x}"

    pairing = InMemoryBrokerPairingAuthority(
        pepper=PAIRING_PEPPER,
        authority=authority,
        code_nonce_factory=nonce,
        credential_factory=lambda: CREDENTIAL,
    )
    kwargs = {
        "rpc": LocalAgentBrokerRpcFacade(authority=authority),
        "state": _DurableState(),
        "material_resolver": _MaterialResolver(),
        "clock": _Clock(),
    }
    if composed:
        handler = PairingAndAdmissionLocalAgentBrokerHttpHandler(
            pairing_authority=pairing,
            admission_reference_factory=_References(),
            **kwargs,
        )
    else:
        handler = PairingEnabledLocalAgentBrokerHttpHandler(pairing_authority=pairing, **kwargs)
    return handler, pairing, authority


def _call(handler, route: str, payload: dict, auth, *, method: str = "POST", content_type: str = "application/json"):
    return handler.handle(
        method=method,
        route=route,
        content_type=content_type,
        body=json.dumps(payload).encode("utf-8"),
        auth=auth,
    )


def _challenge_payload(**overrides) -> dict:
    payload = {
        "account_ref": "account.1",
        "workspace_ref": "workspace.1",
        "now": BASE.isoformat(),
        "ttl_seconds": 300,
    }
    payload.update(overrides)
    return payload


def test_challenge_route_is_scoped_to_the_authenticated_account_and_workspace() -> None:
    handler, pairing, _ = _handler()
    browser = _auth()

    response = _call(handler, PAIRING_CHALLENGE_ROUTE, _challenge_payload(), browser)

    assert response.status == 200
    body = response.body
    assert sorted(body) == sorted({"ok", "challenge", "pairing_code", "pairing_code_returned_once", "proof_transcript"})
    assert body["ok"] is True
    assert body["pairing_code_returned_once"] is True
    assert body["proof_transcript"] == "claw-local-agent-pairing-proof.v1"
    challenge = body["challenge"]
    assert challenge["account_ref"] == "account.1"
    assert challenge["workspace_ref"] == "workspace.1"
    assert challenge["single_use"] is True
    assert challenge["raw_pairing_secret"] is False
    assert datetime.fromisoformat(challenge["issued_at"]).astimezone(timezone.utc) == BASE
    assert body["pairing_code"] not in json.dumps(challenge)
    assert pairing.pending_challenge_count == 1

    assert (
        _call(handler, PAIRING_CHALLENGE_ROUTE, _challenge_payload(), _auth(authenticated=False)).status == 401
    )
    assert _call(handler, PAIRING_CHALLENGE_ROUTE, _challenge_payload(), None).status == 401
    assert (
        _call(handler, PAIRING_CHALLENGE_ROUTE, _challenge_payload(), _auth(tls_verified=False)).status == 403
    )
    assert (
        _call(handler, PAIRING_CHALLENGE_ROUTE, _challenge_payload(account_ref="account.2"), browser).status == 403
    )
    assert (
        _call(handler, PAIRING_CHALLENGE_ROUTE, _challenge_payload(workspace_ref="workspace.2"), browser).status == 403
    )
    assert (
        _call(handler, PAIRING_CHALLENGE_ROUTE, _challenge_payload(ttl_seconds=601), browser).status == 400
    )
    assert _call(handler, PAIRING_CHALLENGE_ROUTE, _challenge_payload(), browser, method="GET").status == 405
    assert (
        _call(handler, PAIRING_CHALLENGE_ROUTE, _challenge_payload(), browser, content_type="text/plain").status
        == 415
    )
    assert _call(handler, PAIRING_CHALLENGE_ROUTE, {"account_ref": "account.1"}, browser).status == 400
    assert _call(handler, PAIRING_CHALLENGE_ROUTE, _challenge_payload(), browser).status == 200
    assert pairing.pending_challenge_count == 2


def _issue(handler, *, browser=None) -> dict:
    response = _call(handler, PAIRING_CHALLENGE_ROUTE, _challenge_payload(), browser or _auth())
    assert response.status == 200
    return response.body


def _redeem_payload(challenge_id: str, *, device_id: str = "device.cli.1", code: str, **overrides) -> dict:
    payload = {
        "challenge_id": challenge_id,
        "device_id": device_id,
        "proof_ref": pairing_proof_ref(
            challenge_id=challenge_id,
            device_id=device_id,
            pairing_code=code,
        ),
        "now": BASE.isoformat(),
    }
    payload.update(overrides)
    return payload


def test_redeem_route_admits_a_device_that_never_had_a_broker_credential() -> None:
    handler, _, authority = _handler()
    issued = _issue(handler)
    challenge_id = issued["challenge"]["challenge_id"]
    device = _auth(principal_ref="device.cli.1", authenticated=False)

    response = _call(
        handler,
        PAIRING_REDEEM_ROUTE,
        _redeem_payload(challenge_id, code=issued["pairing_code"]),
        device,
    )

    assert response.status == 200
    body = response.body
    assert sorted(body) == sorted({"ok", "enrollment", "credential_b64", "credential_returned_once"})
    assert body["credential_returned_once"] is True
    enrollment = body["enrollment"]
    assert enrollment["device_id"] == "device.cli.1"
    assert enrollment["account_ref"] == "account.1"
    assert enrollment["workspace_ref"] == "workspace.1"
    assert enrollment["credential_generation"] == 1
    assert enrollment["server_owned_binding_refs"] is True
    assert enrollment["raw_device_credential"] is False
    credential_b64 = body["credential_b64"]
    assert base64.b64decode(credential_b64, validate=True) == CREDENTIAL
    assert credential_b64 not in json.dumps(enrollment)

    # The returned credential is a working canonical broker credential.
    session = _call(
        handler,
        "/session",
        {
            "session_id": "session.pairing.http.1",
            "binding_ref": enrollment["binding_ref"],
            "credential_b64": credential_b64,
            "account_ref": "account.1",
            "workspace_ref": "workspace.1",
            "now": BASE.isoformat(),
            "ttl_seconds": 900,
        },
        _auth(principal_ref="device.cli.1"),
    )
    assert session.status == 200
    assert session.body["ok"] is True
    assert session.body["session"]["binding_ref"] == enrollment["binding_ref"]

    replay = _call(
        handler,
        PAIRING_REDEEM_ROUTE,
        _redeem_payload(challenge_id, code=issued["pairing_code"]),
        device,
    )
    assert replay.status == 400
    assert replay.body["error"]["code"] == "pairing_challenge_already_redeemed"
    assert len(authority._bindings) == 1


def test_redeem_route_requires_the_exact_proof_and_a_trusted_tls_attestation() -> None:
    handler, _, authority = _handler()
    issued = _issue(handler)
    challenge_id = issued["challenge"]["challenge_id"]
    device = _auth(principal_ref="device.cli.1", authenticated=False)
    payload = _redeem_payload(challenge_id, code=issued["pairing_code"])

    missing_tls = _call(
        handler,
        PAIRING_REDEEM_ROUTE,
        payload,
        _auth(principal_ref="device.cli.1", authenticated=False, tls_verified=False),
    )
    assert missing_tls.status == 403
    assert missing_tls.body["error"]["code"] == "local_agent_http_tls_required"
    assert _call(handler, PAIRING_REDEEM_ROUTE, payload, None).status == 401

    wrong_code = _call(handler, PAIRING_REDEEM_ROUTE, _redeem_payload(challenge_id, code="0" * 32), device)
    assert wrong_code.status == 400
    assert wrong_code.body["error"]["code"] == "invalid_pairing_proof"

    wrong_device_payload = _redeem_payload(challenge_id, code=issued["pairing_code"])
    wrong_device_payload["device_id"] = "device.cli.2"
    wrong_device = _call(
        handler,
        PAIRING_REDEEM_ROUTE,
        wrong_device_payload,
        _auth(principal_ref="device.cli.2", authenticated=False),
    )
    assert wrong_device.status == 400
    assert wrong_device.body["error"]["code"] == "invalid_pairing_proof"

    unknown = _call(
        handler,
        PAIRING_REDEEM_ROUTE,
        _redeem_payload("pairing." + "f" * 32, code=issued["pairing_code"]),
        device,
    )
    assert unknown.status == 400
    assert unknown.body["error"]["code"] == "pairing_challenge_not_found"

    self_asserted = _call(
        handler,
        PAIRING_REDEEM_ROUTE,
        _redeem_payload(challenge_id, code=issued["pairing_code"], account_ref="account.2"),
        device,
    )
    assert self_asserted.status == 400
    assert self_asserted.body["error"]["code"] == "local_agent_http_invalid_request"

    wrong_principal = _call(handler, PAIRING_REDEEM_ROUTE, payload, _auth(principal_ref="device.other"))
    assert wrong_principal.status == 403
    assert authority._bindings == {}

    # The challenge survives every rejected attempt above and still redeems exactly once.
    accepted = _call(handler, PAIRING_REDEEM_ROUTE, payload, device)
    assert accepted.status == 200
    assert accepted.body["ok"] is True


def test_pairing_and_admission_routes_compose_on_one_edge_handler() -> None:
    handler, _, authority = _handler(composed=True)
    issued = _issue(handler)
    challenge_id = issued["challenge"]["challenge_id"]
    device = _auth(principal_ref="device.cli.1", authenticated=False)
    redeemed = _call(
        handler,
        PAIRING_REDEEM_ROUTE,
        _redeem_payload(challenge_id, code=issued["pairing_code"]),
        device,
    )
    assert redeemed.status == 200
    enrollment = redeemed.body["enrollment"]

    session = _call(
        handler,
        "/session",
        {
            "session_id": "session.pairing.composed.1",
            "binding_ref": enrollment["binding_ref"],
            "credential_b64": redeemed.body["credential_b64"],
            "account_ref": "account.1",
            "workspace_ref": "workspace.1",
            "now": BASE.isoformat(),
            "ttl_seconds": 900,
        },
        _auth(principal_ref="device.cli.1"),
    )
    assert session.body["ok"] is True

    command = authority.enqueue_command(
        command_id="command.composed.1",
        binding_ref=enrollment["binding_ref"],
        run_id="run.composed.1",
        tool_request_ref="tool.request.composed.1",
        request_fingerprint="a" * 64,
        now=BASE,
    )
    admission = _call(
        handler,
        "/admission",
        {
            "session_id": "session.pairing.composed.1",
            "binding_ref": enrollment["binding_ref"],
            "credential_b64": redeemed.body["credential_b64"],
            "command_id": command.command_id,
            "request_fingerprint": command.request_fingerprint,
            "request_id": "request.pairing.composed.1",
            "now": BASE.isoformat(),
        },
        _auth(principal_ref="device.cli.1"),
    )
    assert admission.status == 200
    assert admission.body["ok"] is True
    assert admission.body["admission"]["admission_ref"] == ADMISSION_REF
    assert admission.body["admission"]["evidence_ref"] == EVIDENCE_REF
    assert admission.body["admission"]["request_id"] == "request.pairing.composed.1"
    assert authority._commands[command.command_id].state.value == "admitted"

    unknown = _call(handler, "/v1/broker/unknown", _challenge_payload(), _auth())
    assert unknown.status == 404
    rendered = handler.safe_dict()
    assert rendered["pairing_and_admission_composed"] is True
    assert rendered["single_deployable_edge_handler"] is True
    assert rendered["pairing_routes"] == ["/v1/broker/pairings/challenge", "/v1/broker/pairings/redeem"]


def test_pairing_http_truth_constants_do_not_overclaim() -> None:
    assert PAIRING_HTTP_BOUNDARY is True
    assert PAIRING_CHALLENGE_ROUTES == ("/v1/broker/pairings/challenge", "/v1/broker/pairings/redeem")
    assert PAIRING_REDEEM_REQUIRES_TLS_ATTESTATION is True
    assert PAIRING_REDEEM_PROOF_VERIFIED_BEFORE_BINDING is True
    assert PAIRING_REDEEM_REQUIRES_DEVICE_CREDENTIAL is False
    assert PAIRING_CODE_REUSABLE is False
    assert SELF_ASSERTED_ACCOUNT_WORKSPACE_AUTHORITY is False
    assert RAW_PAIRING_CODE_LOGGED is False
    assert RAW_DEVICE_CREDENTIAL_LOGGED is False
    assert PUBLIC_PAIRING_EDGE_SERVICE_CONFIGURED is False
    assert PRODUCTION_PAIRING_ENDPOINT_CONFIGURED is False
    assert PRODUCTION_READY is False

    handler, _, _ = _handler()
    rendered = handler.safe_dict()
    assert rendered["pairing_redeem_requires_device_credential"] is False
    assert rendered["pairing_code_reusable"] is False
    assert rendered["raw_pairing_code_logged"] is False
    assert rendered["self_asserted_account_workspace_authority"] is False
