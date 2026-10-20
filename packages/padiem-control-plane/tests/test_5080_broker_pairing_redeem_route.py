"""#5080: the device-facing one-time enrollment redemption on the broker surface.

A device that holds no broker credential yet reaches
``/v1/broker/pairings/redeem`` with the canonical pairing possession proof
over the one-time pairing code. The credential is returned exactly once and the
account, workspace, consent and owner scope always come from the stored
challenge, never from the request body.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "padiem-control-plane"))
sys.path.insert(0, str(ROOT / "packages" / "padiem-control-plane" / "padiem_control_plane"))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_agent_broker_device_http as device_http  # noqa: E402
from test_local_agent_broker_device_http import (  # noqa: E402
    AUTHORITY_REF, PEPPER, _DurableMemoryStatePort,
)
from padiem_control_plane.contracts import ControlPlaneContractError  # noqa: E402

PROOF = "pairing-proof:" + "a" * 64
NOW = "2026-10-20T00:00:00Z"


class _FakeAuthority:
    def __init__(self, *, refuse: bool = False) -> None:
        self.refuse = refuse
        self.redeemed: list[dict[str, Any]] = []
        self.binding = SimpleNamespace(
            consent_ref="consent.1",
            owner_ref="owner.1",
            account_ref="account.1",
            workspace_ref="workspace.1",
        )

    def enrollment_binding(self, *, challenge_id: str, now: Any) -> Any:
        if self.refuse:
            raise ControlPlaneContractError("enrollment_challenge_not_found", "unknown challenge")
        return self.binding

    def redeem_enrollment(self, **kwargs: Any) -> tuple[Any, bytes]:
        self.redeemed.append(kwargs)
        enrollment = SimpleNamespace(
            device_id=kwargs["device_id"],
            challenge_id=kwargs["challenge_id"],
            safe_dict=lambda: {
                "binding_ref": "binding.1",
                "device_id": kwargs["device_id"],
                "credential_generation": 1,
            },
        )
        return enrollment, b"canonical-credential-bytes"


def _service(*, authority: Any = None, refuse: bool = False) -> Any:
    return device_http.LocalAgentBrokerDeviceHttpService(
        state_port=_DurableMemoryStatePort(),
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        rpc_factory=lambda: None,
        http_state=None,
        material_resolver=None,
        session_open_transaction=lambda operation: operation(),
        clock=lambda: __import__("datetime").datetime(
            2026, 10, 20, 0, 0, tzinfo=__import__("datetime").timezone.utc
        ),
        pairing_authority=authority if authority is not None else _FakeAuthority(refuse=refuse),
    )


def _envelope(route: str, body: dict[str, Any]) -> dict[str, Any]:
    raw = json.dumps(body).encode("utf-8")
    return {
        "method": "POST",
        "route": route,
        "content_type": "application/json",
        "body_b64": base64.b64encode(raw).decode("ascii"),
        "tls_verified": True,
    }


def _redeem_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "challenge_id": "challenge.1",
        "device_id": "device.1",
        "proof_ref": PROOF,
        "now": NOW,
    }
    body.update(overrides)
    return body


def test_the_redeem_route_returns_the_credential_exactly_once() -> None:
    authority = _FakeAuthority()
    service = _service(authority=authority)
    response = service.handle(
        _envelope(device_http.PAIRING_REDEEM_DEVICE_ROUTE, _redeem_body())
    )
    assert response["status"] == 200
    body = response["body"]
    assert body["ok"] is True
    assert body["credential_returned_once"] is True
    assert base64.b64decode(body["credential_b64"]) == b"canonical-credential-bytes"
    assert body["enrollment"]["binding_ref"] == "binding.1"


def test_the_scope_comes_from_the_stored_challenge_never_from_the_request() -> None:
    authority = _FakeAuthority()
    service = _service(authority=authority)
    response = service.handle(
        _envelope(device_http.PAIRING_REDEEM_DEVICE_ROUTE, _redeem_body())
    )
    assert response["status"] == 200
    assert len(authority.redeemed) == 1
    call = authority.redeemed[0]
    assert call["consent_ref"] == "consent.1"
    assert call["owner_ref"] == "owner.1"
    assert call["account_ref"] == "account.1"
    assert call["workspace_ref"] == "workspace.1"
    assert call["challenge_id"] == "challenge.1"
    assert call["device_id"] == "device.1"
    assert call["proof_ref"] == PROOF


def test_an_extra_body_key_is_refused() -> None:
    service = _service()
    response = service.handle(
        _envelope(
            device_http.PAIRING_REDEEM_DEVICE_ROUTE,
            _redeem_body(account_ref="attacker.account"),
        )
    )
    assert response["status"] == 400
    assert response["body"]["ok"] is False


def test_a_non_canonical_proof_is_refused() -> None:
    service = _service()
    for proof in ("pairing-proof:zz", "not-a-proof", "pairing-proof:" + "a" * 63):
        response = service.handle(
            _envelope(device_http.PAIRING_REDEEM_DEVICE_ROUTE, _redeem_body(proof_ref=proof))
        )
        assert response["status"] == 400, proof


def test_an_unknown_challenge_does_not_reveal_that_it_never_existed() -> None:
    service = _service(refuse=True)
    response = service.handle(
        _envelope(device_http.PAIRING_REDEEM_DEVICE_ROUTE, _redeem_body())
    )
    assert response["status"] == 404
    assert response["body"]["error"]["code"] == "local_agent_http_route_not_found"


def test_without_a_configured_pairing_authority_the_route_refuses_closed() -> None:
    service = device_http.LocalAgentBrokerDeviceHttpService(
        state_port=_DurableMemoryStatePort(),
        pepper=PEPPER,
        authority_ref=AUTHORITY_REF,
        rpc_factory=lambda: None,
        http_state=None,
        material_resolver=None,
        session_open_transaction=lambda operation: operation(),
    )
    response = service.handle(
        _envelope(device_http.PAIRING_REDEEM_DEVICE_ROUTE, _redeem_body())
    )
    assert response["status"] == 503
    assert response["body"]["error"]["code"] == "local_agent_http_pairing_unavailable"


def test_the_existing_device_routes_still_require_a_broker_credential() -> None:
    """The new route must not open the credential-authenticated surface."""
    service = _service()
    for route in ("/session", "/poll", "/material", "/acknowledge", "/text-result"):
        response = service.handle(_envelope(route, _redeem_body()))
        assert response["status"] in (400, 401), route
        assert response["body"]["ok"] is False, route


def test_the_route_constant_matches_the_canonical_pairing_surface() -> None:
    from padiem_control_plane.local_agent_broker_pairing_http import PAIRING_REDEEM_ROUTE

    assert device_http.PAIRING_REDEEM_DEVICE_ROUTE == PAIRING_REDEEM_ROUTE
    assert device_http.PAIRING_REDEEM_DEVICE_ROUTE in device_http.DEVICE_HTTP_ROUTES


def test_the_route_never_runs_without_verified_tls() -> None:
    service = _service()
    envelope = _envelope(device_http.PAIRING_REDEEM_DEVICE_ROUTE, _redeem_body())
    envelope["tls_verified"] = False
    response = service.handle(envelope)
    assert response["status"] == 403
    assert response["body"]["error"]["code"] == "local_agent_http_tls_required"
