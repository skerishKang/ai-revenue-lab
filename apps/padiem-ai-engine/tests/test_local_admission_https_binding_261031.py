"""The COM2 Engine host reaches the Control Plane admission authority over HTTPS.

On Cloudflare the Engine calls the admission authority through the private
Service Binding ``CONTROL_PLANE_ENGINE_ADMISSION``. This host has no binding, so
``app.local_admission_binding`` puts a binding-shaped HTTPS stand-in on the host
env. These tests prove three things and nothing more:

* the proof the host signs is the one the Control Plane ingress already
  verifies (#5573 A2, #6417), recomputed here independently rather than by
  importing the same helper — including the signed request id the ingress
  consumes to refuse a replay;
* an allowed snapshot plus reservation runs the turn through the reviewed
  adapter and the Engine gate unchanged;
* a denied grant, a bad proof, an unreachable authority or a missing/partial
  configuration all stay fail-closed — no path here can allow a run the
  authority did not grant.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.execution_admission import ExecutionAdmissionError, ExecutionAdmissionRequest
from app.execution_admission_gate import resolve_and_require_trusted_admission
from app.local_admission_binding import (
    ADMISSION_ORIGIN_ENV,
    ADMISSION_SECRET_ENV,
    HttpsAdmissionBinding,
    RPC_MAX_ATTEMPTS,
    admission_binding_for,
)
from app.tenant_auth import ControlPlaneTenantAdmissionAdapter

SECRET = "com2-host-admission-secret-0123456789abcdef"
ORIGIN = "https://engine-admission.padiem.internal"
SUBJECT = "subject:padiem:user:com2"
PRODUCT = "b62"
FINGERPRINT = "a" * 64
CAPABILITY = "orchestration.run"
RESERVATION_REF = "res-com2-0001"


def _now() -> datetime:
    return datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def _snapshot(*, allowed: bool = True, limit: int | None = None) -> dict[str, object]:
    return {
        "snapshot_id": "snap-com2-0001",
        "product_id": PRODUCT,
        "subject": {"subject_type": "user", "subject_id": SUBJECT},
        "revision": "rev-41",
        "issued_at": (_now() - timedelta(minutes=1)).isoformat(),
        "expires_at": (_now() + timedelta(minutes=10)).isoformat(),
        "grants": [{"key": CAPABILITY, "allowed": allowed, "limit": limit}],
    }


def _reservation() -> dict[str, object]:
    return {
        "reservation_ref": RESERVATION_REF,
        "admitted": True,
        "reserved_at": (_now() - timedelta(seconds=1)).isoformat(),
        "expires_at": (_now() + timedelta(minutes=5)).isoformat(),
    }


class _ControlPlaneIngress:
    """A stand-in for the Control Plane private RPC ingress.

    The proof check below is written out inline — the canonical string, the
    header names and the comparison — so a change to the shared helper cannot
    silently agree with itself.
    """

    def __init__(
        self,
        *,
        snapshot: dict[str, object] | None = None,
        secret: str = SECRET,
        unreserved: bool = False,
        replay_refusals: int = 0,
    ) -> None:
        self.secret = secret
        self.snapshot = _snapshot() if snapshot is None else snapshot
        self.unreserved = unreserved
        self.replay_refusals = replay_refusals
        self.calls: list[str] = []
        self.service_ids: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method_name = path.rsplit("/", 1)[-1]
        body = request.content
        at = request.headers.get("x-padiem-service-at", "")
        service_id = request.headers.get("x-padiem-service-id", "")
        provided = request.headers.get("x-padiem-service-proof", "")
        signed = b"\n".join(
            (
                b"v2",
                b"POST",
                path.encode("utf-8"),
                at.encode("ascii"),
                service_id.encode("utf-8"),
                body,
            )
        )
        expected = "v2=" + hmac.new(
            self.secret.encode("utf-8"), signed, hashlib.sha256
        ).hexdigest()
        if not service_id or provided != expected:
            return httpx.Response(
                401, json={"ok": False, "error": {"code": "proof_invalid"}}
            )
        self.service_ids.append(service_id)
        if self.replay_refusals > 0:
            self.replay_refusals -= 1
            return httpx.Response(
                409, json={"ok": False, "error": {"code": "rpc_replay_detected"}}
            )
        self.calls.append(method_name)
        if method_name == "fetch_entitlement_snapshot":
            payload = json.loads(body)
            assert payload == {
                "product_id": PRODUCT,
                "subject": {"subject_type": "user", "subject_id": SUBJECT},
            }
            return httpx.Response(200, json={"ok": True, "snapshot": self.snapshot})
        if method_name == "reserve_usage":
            payload = json.loads(body)
            assert set(payload) == {"reservation"}
            if self.unreserved:
                return httpx.Response(
                    200,
                    json={
                        "ok": True,
                        "reservation": {
                            **_reservation(),
                            "admitted": False,
                        },
                    },
                )
            return httpx.Response(200, json={"ok": True, "reservation": _reservation()})
        if method_name == "record_usage":
            return httpx.Response(
                200, json={"ok": True, "receipt": {"accepted": True, "event_id": "u-1"}}
            )
        return httpx.Response(404, json={"ok": False, "error": {"code": "rpc_unknown"}})


def _adapter(ingress: _ControlPlaneIngress) -> ControlPlaneTenantAdmissionAdapter:
    from app.control_plane_trust_client import CloudflareControlPlaneTrustClient

    client = httpx.AsyncClient(transport=httpx.MockTransport(ingress))
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, client=client)
    return ControlPlaneTenantAdmissionAdapter(
        client=CloudflareControlPlaneTrustClient(binding),
        clock=_now,
    )


def _request() -> ExecutionAdmissionRequest:
    return ExecutionAdmissionRequest(
        app_id="padiem-chat",
        subject_id=SUBJECT,
        capability=CAPABILITY,
        request_fingerprint=FINGERPRINT,
        usage_reservation_identity="run-com2-0001",
    )


def _resolve(adapter: object) -> object:
    return asyncio.run(
        resolve_and_require_trusted_admission(adapter=adapter, request=_request(), now=_now())
    )


def test_allowed_snapshot_and_reservation_run_the_turn() -> None:
    ingress = _ControlPlaneIngress()
    admission = _resolve(_adapter(ingress))

    assert admission.allowed is True
    assert admission.permission_product_id == PRODUCT
    assert admission.capability == CAPABILITY
    assert admission.usage_reservation is not None
    assert admission.usage_reservation.reservation_ref == RESERVATION_REF
    assert ingress.calls == ["fetch_entitlement_snapshot", "reserve_usage"]

    # Two calls are two requests; the ingress would refuse a repeated id.
    assert len(ingress.service_ids) == 2
    assert len(set(ingress.service_ids)) == 2


def test_a_replay_refusal_is_retried_under_a_new_id() -> None:
    ingress = _ControlPlaneIngress(replay_refusals=1)
    admission = _resolve(_adapter(ingress))

    assert admission.allowed is True
    assert ingress.calls == ["fetch_entitlement_snapshot", "reserve_usage"]
    # The refused attempt, its retry, and the reservation: all different ids.
    assert len(ingress.service_ids) == 3
    assert len(set(ingress.service_ids)) == 3


def test_a_target_that_keeps_refusing_is_bounded_and_stays_closed() -> None:
    ingress = _ControlPlaneIngress(replay_refusals=99)
    binding = HttpsAdmissionBinding(
        ORIGIN, SECRET,
        client=httpx.AsyncClient(transport=httpx.MockTransport(ingress)),
    )
    with pytest.raises(RuntimeError):
        asyncio.run(binding.fetch_entitlement_snapshot({"product_id": PRODUCT}))
    assert len(ingress.service_ids) == RPC_MAX_ATTEMPTS
    assert len(set(ingress.service_ids)) == RPC_MAX_ATTEMPTS

    # Through the reviewed adapter the same cap is a fail-closed 503.
    with pytest.raises(ExecutionAdmissionError) as refused:
        _resolve(_adapter(_ControlPlaneIngress(replay_refusals=99)))
    assert refused.value.code == "entitlement_unavailable"
    assert refused.value.status_code == 503


def test_a_plain_failure_is_not_retried() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(500, json={"ok": False})

    binding = HttpsAdmissionBinding(
        ORIGIN, SECRET,
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RuntimeError):
        asyncio.run(binding.fetch_entitlement_snapshot({"product_id": PRODUCT}))
    assert calls == [1]


def test_denied_grant_is_a_403_and_never_reserves() -> None:
    ingress = _ControlPlaneIngress(snapshot=_snapshot(allowed=False))
    with pytest.raises(ExecutionAdmissionError) as refused:
        _resolve(_adapter(ingress))

    assert refused.value.code == "entitlement_denied"
    assert refused.value.status_code == 403
    assert ingress.calls == ["fetch_entitlement_snapshot"]


def test_refused_reservation_is_a_403() -> None:
    ingress = _ControlPlaneIngress(unreserved=True)
    with pytest.raises(ExecutionAdmissionError) as refused:
        _resolve(_adapter(ingress))

    assert refused.value.code == "entitlement_denied"
    assert refused.value.status_code == 403


def test_wrong_signature_never_reaches_the_authority() -> None:
    ingress = _ControlPlaneIngress(secret="another-secret-0123456789abcdefghij")
    with pytest.raises(ExecutionAdmissionError) as refused:
        _resolve(_adapter(ingress))

    assert refused.value.code == "entitlement_unavailable"
    assert refused.value.status_code == 503
    assert ingress.calls == []


def test_unreachable_authority_is_a_503() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("unreachable", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    binding = HttpsAdmissionBinding(ORIGIN, SECRET, client=client)
    from app.control_plane_trust_client import CloudflareControlPlaneTrustClient

    adapter = ControlPlaneTenantAdmissionAdapter(
        client=CloudflareControlPlaneTrustClient(binding),
        clock=_now,
    )
    with pytest.raises(ExecutionAdmissionError) as refused:
        _resolve(adapter)

    assert refused.value.code == "entitlement_unavailable"
    assert refused.value.status_code == 503


def test_missing_or_partial_configuration_leaves_the_binding_absent() -> None:
    assert admission_binding_for({}) == {}
    # A half-configured pair is absent, never permissive.
    assert admission_binding_for({ADMISSION_ORIGIN_ENV: ORIGIN}) == {}
    assert admission_binding_for({ADMISSION_SECRET_ENV: SECRET}) == {}
    assert admission_binding_for({ADMISSION_ORIGIN_ENV: "http://insecure", ADMISSION_SECRET_ENV: SECRET}) == {}
    assert admission_binding_for({ADMISSION_ORIGIN_ENV: ORIGIN, ADMISSION_SECRET_ENV: "short"}) == {}
    assert admission_binding_for({ADMISSION_ORIGIN_ENV: ORIGIN + "/path", ADMISSION_SECRET_ENV: SECRET}) == {}

    configured = admission_binding_for(
        {ADMISSION_ORIGIN_ENV: ORIGIN, ADMISSION_SECRET_ENV: SECRET}
    )
    assert set(configured) == {"CONTROL_PLANE_ENGINE_ADMISSION"}


def test_absent_binding_keeps_the_engine_gate_closed() -> None:
    with pytest.raises(ExecutionAdmissionError) as refused:
        _resolve(None)

    assert refused.value.code == "entitlement_unavailable"
    assert refused.value.status_code == 503


def test_host_runtime_env_carries_the_binding_only_when_configured() -> None:
    from app import local_runtime

    empty = local_runtime._local_bindings({})
    assert "CONTROL_PLANE_ENGINE_ADMISSION" not in empty

    configured = local_runtime._local_bindings(
        {ADMISSION_ORIGIN_ENV: ORIGIN, ADMISSION_SECRET_ENV: SECRET}
    )
    assert isinstance(configured["CONTROL_PLANE_ENGINE_ADMISSION"], HttpsAdmissionBinding)
