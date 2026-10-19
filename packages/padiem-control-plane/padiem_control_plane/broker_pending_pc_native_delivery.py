"""#4139 existing Broker DO: EXACT SAME native WSS protected credential transport.

Private, default-OFF operator review only. No additional DO, HTTP endpoint or
credential authority. B54's original CanonicalConnectorEnrollmentAsyncHost
remains the ONLY authorized source of canonical Broker redeem/revoke, fresh
Identity grant checks and credential-keyed protected-store install proof.

This DO ONLY verifies the still-live PC channel, routes a one-use credential
over that same accepted WSS and authenticates the install_ack HMAC with the
original canonical Broker lease/counter. It does not infer Windows persistence,
produce paired_offline, or grant command access.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
from datetime import datetime, timezone
import json
import re
from typing import Any

from .broker_pending_pc_identity_handoff import _actor, BrokerPcIdentityHandoffDenied

NATIVE_PC_DELIVERY_PRODUCTION_ENABLED = False
NATIVE_PC_DELIVERY_PUBLIC_ROUTE_MOUNTED = False
_FLAG = "LOCAL_AGENT_BROKER_PENDING_PC_NATIVE_DELIVERY_ENABLED"
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_LINK = re.compile(r"^link\.[0-9a-f]{32}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_PUBLIC_FIELDS = frozenset({
    "binding_ref", "device_id", "account_ref", "workspace_ref", "credential_ref",
    "credential_generation", "credential_expires_at",
})
_ACK_FIELDS = frozenset({
    "challenge_id", "device_id", "binding_ref", "credential_generation",
    "proof_kind", "transcript_version", "local_store_confirmed", "proof_hex",
})
MAX_RAW_CREDENTIAL = 4096
MAX_ACK_BYTES = 3072


class NativePcDeliveryDenied(RuntimeError):
    """Sanitized; must never contain a raw credential or PC proof."""


def _started(owner_do: Any, payload: Any, keys: set[str], *, completed_ack: bool = False):
    if type(payload) is not dict or set(payload) != keys:
        raise NativePcDeliveryDenied("native_pc_private_fields_invalid")
    if (
        getattr(owner_do.env, _FLAG, None) != "enabled"
        or type(payload["request_ref"]) is not str
        or _LINK.fullmatch(payload["request_ref"]) is None
    ):
        raise NativePcDeliveryDenied("native_pc_delivery_disabled")
    try:
        actor = _actor(owner_do, payload["request_ref"])
        base = actor._canonical_bootstrap
        if (
            getattr(actor, "_identity_proof_claimed", False) is not True
            or type(base._lease) is not str or _REF.fullmatch(base._lease) is None
            or base._lease_expires_at is None
            or datetime.now(timezone.utc) >= base._lease_expires_at
            or actor._socket.closed is not False
            or actor._disconnected is not False
            or getattr(actor, "_native_delivery_complete", False) is not completed_ack
        ):
            raise ValueError("same WSS already lost or reserved")
        return actor
    except Exception:
        raise NativePcDeliveryDenied("native_pc_live_session_unavailable") from None


def _match(actor: Any, payload: dict[str, Any], lease: bool = True) -> None:
    if (
        payload.get("challenge_id") != actor._approved_challenge
        or payload.get("device_id") != actor._device
        or (lease and payload.get("lease_ref") != actor._canonical_bootstrap._lease)
    ):
        raise NativePcDeliveryDenied("native_pc_session_mismatch")


def _lease_reply(actor: Any) -> dict[str, Any]:
    return {
        "request_ref": actor._request_ref,
        "challenge_id": actor._approved_challenge,
        "device_id": actor._device,
        "lease_ref": actor._canonical_bootstrap._lease,
        "expires_at": actor._canonical_bootstrap._lease_expires_at.isoformat(),
        "authenticated": True, "credential_issued": False,
    }


async def reserve_native_pc_gateway(owner_do: Any, payload: Any) -> dict[str, Any]:
    actor = _started(owner_do, payload, {
        "request_ref", "challenge_id", "device_id",
    })
    _match(actor, payload, lease=False)
    if getattr(actor, "_native_gateway_reserved", False) is not False:
        raise NativePcDeliveryDenied("native_pc_gateway_already_reserved")
    # Irrevocably claim BEFORE replying; uncertain Service Binding responses
    # MUST NOT permit a second redemption or a second transfer.
    actor._native_gateway_reserved = True
    return _lease_reply(actor)


async def authenticate_native_pc_gateway(owner_do: Any, payload: Any) -> dict[str, Any]:
    actor = _started(owner_do, payload, {
        "request_ref", "challenge_id", "device_id", "lease_ref",
    })
    _match(actor, payload)
    if getattr(actor, "_native_gateway_reserved", False) is not True:
        raise NativePcDeliveryDenied("native_pc_gateway_not_reserved")
    return {
        "request_ref": actor._request_ref,
        "challenge_id": actor._approved_challenge,
        "device_id": actor._device,
        "lease_ref": actor._canonical_bootstrap._lease,
        "authenticated": True, "credential_issued": False,
    }


def _credential(value: Any) -> bytes:
    if type(value) is not str or len(value) > 5500:
        raise NativePcDeliveryDenied("native_pc_credential_invalid")
    try:
        binary = base64.b64decode(value, validate=True)
        if (
            not 16 <= len(binary) <= MAX_RAW_CREDENTIAL
            or base64.b64encode(binary).decode("ascii") != value
        ):
            raise ValueError("wrong length/noncanonical")
        return binary
    except (ValueError, binascii.Error):
        raise NativePcDeliveryDenied("native_pc_credential_invalid") from None


async def transfer_native_pc_credential_once(owner_do: Any, payload: Any) -> dict[str, Any]:
    actor = _started(owner_do, payload, {
        "request_ref", "challenge_id", "device_id", "lease_ref",
        "binding", "credential_b64",
    })
    _match(actor, payload)
    if (
        getattr(actor, "_native_gateway_reserved", False) is not True
        or getattr(actor, "_native_credential_attempted", False) is not False
        or type(payload["binding"]) is not dict
        or set(payload["binding"]) != _PUBLIC_FIELDS
    ):
        raise NativePcDeliveryDenied("native_pc_transfer_not_authorized")
    binding = payload["binding"]
    if (
        binding["device_id"] != actor._device
        or any(type(binding.get(k)) is not str or _REF.fullmatch(binding[k]) is None
               for k in ("binding_ref", "device_id", "account_ref", "workspace_ref",
                         "credential_ref"))
        or type(binding.get("credential_generation")) is not int
        or not 1 <= binding["credential_generation"] <= 1_000_000
        or type(binding.get("credential_expires_at")) is not str
    ):
        raise NativePcDeliveryDenied("native_pc_transfer_binding_invalid")
    try:
        expiry = datetime.fromisoformat(
            binding["credential_expires_at"].replace("Z", "+00:00")
        )
        if expiry.tzinfo is None or expiry <= datetime.now(timezone.utc):
            raise ValueError("invalid credential expiry")
    except (ValueError, OverflowError, TypeError):
        raise NativePcDeliveryDenied("native_pc_transfer_expired") from None

    raw = _credential(payload["credential_b64"])
    # One-way NO-RETRY boundary: mark consumed before any native send.
    actor._native_credential_attempted = True
    actor._native_expected_binding = dict(binding)
    actor._native_ack_future = asyncio.get_running_loop().create_future()
    actor._native_delivery_phase = "await_ack"
    try:
        await actor._socket.send_text(json.dumps({
            "type": "credential_once",
            "challenge_id": actor._approved_challenge,
            "device_id": actor._device,
            "lease_ref": actor._canonical_bootstrap._lease,
            "binding": binding,
            "credential_b64": payload["credential_b64"],
        }, separators=(",", ":"), sort_keys=True))
    except Exception:
        actor._native_delivery_phase = "failed"
        actor.mark_disconnected()
        await actor._socket.close()
        raise NativePcDeliveryDenied("native_pc_send_uncertain") from None
    finally:
        # Do not persist decoded raw credential in actor or DO state.
        del raw
    return {"sent_once": True, "credential_installed": False, "registered": False}


def _ack_shape(value: Any, actor: Any) -> dict[str, Any]:
    if (
        type(value) is not dict or set(value) != _ACK_FIELDS
        or value["challenge_id"] != actor._approved_challenge
        or value["device_id"] != actor._device
        or value["binding_ref"] != actor._native_expected_binding["binding_ref"]
        or type(value["credential_generation"]) is not int
        or value["credential_generation"] != actor._native_expected_binding["credential_generation"]
        or value["proof_kind"] != "protected_store_save_readback"
        or value["transcript_version"] != "padiem.connector-device-install-ack.v1"
        or value["local_store_confirmed"] is not True
        or type(value["proof_hex"]) is not str
        or _HEX64.fullmatch(value["proof_hex"]) is None
    ):
        raise NativePcDeliveryDenied("native_pc_ack_invalid")
    return value


def _unique_pairs(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise NativePcDeliveryDenied("native_pc_ack_duplicate_field")
        d[k] = v
    return d


async def native_pc_accept_install_ack(owner_do: Any, actor: Any, raw_frame: Any) -> None:
    """Called ONLY by the same native WebSocket's Cloudflare DO message hook."""
    if (
        type(raw_frame) is not str or not 0 < len(raw_frame) <= 8192
        or getattr(actor, "_native_delivery_phase", None) != "await_ack"
        or actor._socket.closed is not False
    ):
        raise NativePcDeliveryDenied("native_pc_ack_not_expected")
    try:
        wire = json.loads(raw_frame, object_pairs_hook=_unique_pairs)
        if type(wire) is not dict or set(wire) != {
            "type", "counter", "proof_hex", "body_b64",
        } or wire["type"] != "install_ack" or type(wire["counter"]) is not int             or wire["counter"] != 2 or type(wire["proof_hex"]) is not str             or _HEX64.fullmatch(wire["proof_hex"]) is None:
            raise ValueError("wrong envelope")
        encoded = wire["body_b64"]
        if type(encoded) is not str or len(encoded) > 4104:
            raise ValueError("body size")
        raw = base64.b64decode(encoded, validate=True)
        if (
            not raw or len(raw) > MAX_ACK_BYTES
            or base64.b64encode(raw).decode("ascii") != encoded
        ):
            raise ValueError("body encoding")
        ack = _ack_shape(
            json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs),
            actor,
        )
        # Independent ORIGINAL canonical Broker nonce/lease MAC counter=2.
        result = await owner_do.gateway_bootstrap_rpc({
            "operation": "authorize",
            "args": {
                "challenge_id": actor._approved_challenge,
                "device_id": actor._device,
                "lease_ref": actor._canonical_bootstrap._lease,
                "action": "install_ack", "counter": 2,
                "body_b64": encoded, "proof_hex": wire["proof_hex"],
            },
        })
        if (
            type(result) is not dict or set(result) != {"ok", "gateway"}
            or result["ok"] is not True
            or type(result["gateway"]) is not dict
            or set(result["gateway"]) != {
                "challenge_id", "device_id", "lease_ref",
                "action", "counter", "authenticated",
            }
            or result["gateway"]["challenge_id"] != actor._approved_challenge
            or result["gateway"]["device_id"] != actor._device
            or result["gateway"]["lease_ref"] != actor._canonical_bootstrap._lease
            or result["gateway"]["action"] != "install_ack"
            or type(result["gateway"]["counter"]) is not int
            or result["gateway"]["counter"] != 2
            or result["gateway"]["authenticated"] is not True
        ):
            raise ValueError("Broker refused signed ACK")
        actor._native_ack_receipt = dict(ack)
        actor._native_delivery_phase = "ack_received"
        pending = actor._native_ack_future
        if pending is not None and not pending.done():
            pending.set_result(dict(ack))
    except Exception:
        actor._native_delivery_phase = "failed"
        future = getattr(actor, "_native_ack_future", None)
        if future is not None and not future.done():
            future.set_exception(NativePcDeliveryDenied("native_pc_ack_unconfirmed"))
            # An abandoned private RPC may not yet be awaiting the Future.
            future.add_done_callback(lambda f: f.exception())
        raise NativePcDeliveryDenied("native_pc_ack_unconfirmed") from None


def _claimed(owner_do: Any, payload: Any, keys: set[str]):
    # _actor normally expects canonical bootstrap identity_required, which
    # remains unchanged after sending a credential and receiving the ACK.
    actor = _started(owner_do, payload, keys)
    _match(actor, payload)
    if (
        getattr(actor, "_native_gateway_reserved", False) is not True
        or getattr(actor, "_native_credential_attempted", False) is not True
    ):
        raise NativePcDeliveryDenied("native_pc_send_not_confirmed")
    return actor


async def receive_native_pc_install_ack(owner_do: Any, payload: Any) -> dict[str, Any]:
    actor = _claimed(owner_do, payload, {
        "request_ref", "challenge_id", "device_id", "lease_ref",
    })
    if getattr(actor, "_native_ack_wait_claimed", False) is not False:
        raise NativePcDeliveryDenied("native_pc_ack_already_claimed")
    actor._native_ack_wait_claimed = True
    future = getattr(actor, "_native_ack_future", None)
    if future is None:
        raise NativePcDeliveryDenied("native_pc_ack_unavailable")
    try:
        ack = await asyncio.wait_for(asyncio.shield(future), timeout=25.0)
        if actor._socket.closed is not False or actor._disconnected:
            raise NativePcDeliveryDenied("native_pc_socket_lost")
        return {"ack": dict(ack), "source_authenticated": True,
                "registered": False}
    except Exception:
        actor._native_delivery_phase = "failed"
        raise NativePcDeliveryDenied("native_pc_ack_unconfirmed") from None


async def authenticate_native_pc_install_ack(owner_do: Any, payload: Any) -> dict[str, Any]:
    actor = _claimed(owner_do, payload, {
        "request_ref", "challenge_id", "device_id", "lease_ref", "ack",
    })
    ack = payload["ack"]
    if (
        getattr(actor, "_native_ack_wait_claimed", False) is not True
        or getattr(actor, "_native_delivery_phase", None) != "ack_received"
        or type(ack) is not dict
        or ack != getattr(actor, "_native_ack_receipt", None)
        or actor._socket.closed is not False
    ):
        raise NativePcDeliveryDenied("native_pc_ack_sender_unconfirmed")
    # The ORIGINAL B54 host will separately verify the keyed DPAPI transcript
    # with the newly redeemed canonical Broker credential and will recheck
    # Identity consent after this receipt. No paired_online claim here.
    actor._native_delivery_complete = True
    return {"source_authenticated": True, "registered": False}


async def complete_native_pc_enrollment(owner_do: Any, payload: Any) -> dict[str, Any]:
    """Send the existing terminal frame AFTER B54 verifies ACK and Identity.

    Private transport only: no new credential, grant or ONLINE projection.
    The original host's final authorization must precede this call.
    """
    actor = _started(owner_do, payload, {
        "request_ref", "challenge_id", "device_id", "lease_ref",
    }, completed_ack=True)
    _match(actor, payload)
    if (getattr(actor, "_native_delivery_phase", None) != "ack_received"
            or getattr(actor, "_native_terminal_attempted", False) is not False):
        raise NativePcDeliveryDenied("native_pc_terminal_not_authorized")
    actor._native_terminal_attempted = True
    try:
        await actor._socket.send_text(json.dumps({
            "type": "terminal", "status": "paired_offline",
            "can_retry_challenge": False,
        }, separators=(",", ":"), sort_keys=True))
    except Exception:
        raise NativePcDeliveryDenied("native_pc_terminal_uncertain") from None
    return {"sent_once": True, "connected": False}
