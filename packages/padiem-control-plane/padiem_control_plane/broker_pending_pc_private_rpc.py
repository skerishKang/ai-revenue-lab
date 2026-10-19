"""#4139 existing canonical Broker DO private owner-to-live-PC RPC.

SOURCE ONLY and default-OFF. The live per-DO actor is attached ONLY by the
server's verified PC WSS handler, not by the owner Worker/browser, a public
route, a new Durable Object or an RPC attach method.

The canonical Broker namespace maps both HTTPS owner's private calls and
accepted PC WSS to the SAME authority-ref DO. A DO eviction/restart drops
this in-memory socket association and refuses approval (no rehydration of a
dead socket from a durable ledger). The ledger itself enforces atomic one-use
request states in the existing SQLite; there is NO separate credential store.

Do NOT activate until the real WSS ingress on this very DO and an Identity
owner-approved B54 caller are verified through integration tests.
"""
from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import re
from typing import Any

_PRIVATE_METHODS_PRODUCTION_ENABLED = False
_OWNER_RPC_MOUNTED = False
_PC_WSS_SAME_BROKER_DO_MOUNTED = False
_PENDING_FLAG = "LOCAL_AGENT_BROKER_PENDING_PC_OWNER_RPC_ENABLED"
_SCHEMA_FLAG = "LOCAL_AGENT_BROKER_PENDING_PC_SCHEMA_INSTALLED"
_REVIEW_SCOPE_FLAG = "LOCAL_AGENT_BROKER_PENDING_PC_RELEASE_SCOPE"
_REVIEW_SCOPE = "isolated-operator-acceptance-4139"
_LIVE_SCOPE = "owner-controlled-production-4139"
_LIVE_ENABLED = "LOCAL_AGENT_BROKER_PENDING_PC_PRODUCTION_ENABLED"
_REF = re.compile(r"^link\.[0-9a-f]{32}$")
_DEVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_CODE = re.compile(r"^[0-9a-f]{32}$")


# Private internal RPC diagnostic. The public owner route still returns its
# original fixed pending_pc_unavailable denial, never these internal details.
_OWNER_DIAGNOSTIC_KEY = "_pending_pc_owner_rpc_failure"
_OWNER_DIAGNOSTIC_CODES = frozenset({
    "private_fields_invalid", "rpc_disabled", "storage_unavailable",
    "live_socket_missing", "actor_unavailable", "actor_refused",
    "owner_scope_invalid", "request_unavailable", "already_used",
    "outbound_channel_unverified", "store_invalid", "store_unavailable",
    "sql_reservation_unconfirmed", "receipt_invalid", "do_rpc_unavailable",
    "private_payload_type_invalid", "private_keys_invalid",
    "private_request_ref_invalid", "private_owner_subject_invalid",
    "private_account_ref_invalid", "private_workspace_ref_invalid",
})

def _owner_rpc_failure(code: str) -> dict[str, str]:
    return {_OWNER_DIAGNOSTIC_KEY: (
        code if code in _OWNER_DIAGNOSTIC_CODES else "actor_refused"
    )}


def _owner_rpc_payload_dict(value: Any) -> dict[str, Any] | None:
    """Canonical RPC bridge conversion, never iterable-pair coercion.

    The private Worker/DO boundary may receive a Pyodide RPC wrapper even
    when the sender used a plain dict. Normalize only a mapping or a
    wrapper's to_py() result that is a mapping; exact keys and values are
    validated independently by the caller.
    """
    if type(value) is dict:
        return dict(value)
    try:
        convert = getattr(value, "to_py", None)
        if callable(convert):
            candidate = convert()
        elif isinstance(value, Mapping):
            candidate = value
        else:
            return None
        if not isinstance(candidate, Mapping):
            return None
        return dict(candidate)
    except Exception:
        # Do not expose a remote exception message or object representation.
        return None


class BrokerPendingPcPrivateRefused(RuntimeError):
    """No code, credential, session, or forged identity is returned."""


def _enabled(env: Any) -> bool:
    return (
        getattr(env, _PENDING_FLAG, None) == "enabled"
        and getattr(env, _SCHEMA_FLAG, None) == "installed"
        and (
            getattr(env, _REVIEW_SCOPE_FLAG, None) == _REVIEW_SCOPE
            or (
                getattr(env, _REVIEW_SCOPE_FLAG, None) == _LIVE_SCOPE
                and getattr(env, _LIVE_ENABLED, None) == "enabled"
            )
        )
    )


def _ref(value: Any) -> bool:
    return type(value) is str and _REF.fullmatch(value) is not None


class CanonicalBrokerPendingPcLiveRPC:
    """Mixin to SAME existing LocalAgentBrokerDurableObject, never a new DO."""

    def _pending_pc_live(self) -> dict[str, Any]:
        if not _enabled(self.env):
            raise BrokerPendingPcPrivateRefused("pending_pc_rpc_disabled")
        try:
            storage = self._storage
            if (
                not callable(getattr(storage, "transactionSync", None))
                or not callable(getattr(getattr(storage, "sql", None), "exec", None))
            ):
                raise BrokerPendingPcPrivateRefused("pending_pc_canonical_storage_unavailable")
        except AttributeError:
            raise BrokerPendingPcPrivateRefused("pending_pc_canonical_storage_unavailable") from None
        if not hasattr(self, "_pending_pc_live_by_ref"):
            self._pending_pc_live_by_ref = {}
        return self._pending_pc_live_by_ref

    def _bind_verified_pc_wss(self, *, request_ref: str, actor: Any) -> None:
        """Only server's SAME DO accepted-PC handler calls this LOCAL method.

        NEVER add _bind_verified_pc_wss to Default WorkerEntrypoint or public
        Durable Object RPC. It requires exact object identity of canonical
        Broker DO storage, the accepted PC WSS, and the actor's persisted ref.
        """
        active = self._pending_pc_live()
        if not _ref(request_ref):
            raise BrokerPendingPcPrivateRefused("pending_pc_invalid_ref")
        try:
            if (
                actor._request_ref != request_ref
                or actor._broker._store is not self._storage
                or actor._gateway._socket is not actor._socket
                or actor._ready is not True
                or actor._disconnected is not False
                or getattr(actor._socket, "closed", None) is not False
                or not callable(getattr(actor, "reserve_once", None))
                or not callable(getattr(actor, "deliver_once", None))
                or not callable(getattr(actor, "mark_disconnected", None))
            ):
                raise ValueError("not the same canonical live Broker PC actor")
        except (AttributeError, TypeError, ValueError):
            raise BrokerPendingPcPrivateRefused("pending_pc_actor_unverified") from None
        if request_ref in active:
            raise BrokerPendingPcPrivateRefused("pending_pc_actor_duplicate")
        # Strictly DO-instance-local; no global module dictionary.
        active[request_ref] = actor

    def _pc_actor(self, request_ref: str) -> Any:
        active = self._pending_pc_live()
        if not _ref(request_ref):
            raise BrokerPendingPcPrivateRefused("pending_pc_invalid_ref")
        actor = active.get(request_ref)
        if actor is None:
            raise BrokerPendingPcPrivateRefused("pending_pc_live_socket_missing")
        try:
            if (
                actor._request_ref != request_ref
                or actor._broker._store is not self._storage
                or actor._gateway._socket is not actor._socket
                or actor._disconnected
                or getattr(actor._socket, "closed", None) is not False
                or actor._expiry is None
                or datetime.now(timezone.utc) >= actor._expiry
            ):
                raise ValueError("outdated per-DO WSS")
        except (AttributeError, TypeError, ValueError):
            active.pop(request_ref, None)
            raise BrokerPendingPcPrivateRefused("pending_pc_live_socket_missing") from None
        return actor

    async def reserve_pending_pc_link(self, payload: dict) -> dict[str, Any]:
        """Private same-DO RPC: owner must already be verified by B54 Worker."""
        payload = _owner_rpc_payload_dict(payload)
        if payload is None or set(payload) != {"request_ref"}:
            raise BrokerPendingPcPrivateRefused("pending_pc_private_fields_invalid")
        actor = self._pc_actor(payload["request_ref"])
        try:
            receipt = await actor.reserve_once(request_ref=payload["request_ref"])
        except Exception:
            raise BrokerPendingPcPrivateRefused("pending_pc_reservation_unconfirmed") from None
        if (
            type(receipt) is not dict
            or set(receipt) != {
                "request_ref", "device_id", "expires_at",
                "device_possession_verified", "connected_to_outbound_channel",
                "reserved_once",
            }
            or receipt["request_ref"] != payload["request_ref"]
            or any(receipt.get(k) is not True for k in (
                "device_possession_verified", "connected_to_outbound_channel",
                "reserved_once",
            ))
        ):
            raise BrokerPendingPcPrivateRefused("pending_pc_reservation_unconfirmed")
        return receipt

    async def reserve_pending_pc_owner_intent(self, payload: dict) -> dict[str, Any]:
        """Exact one-use RPC; relay bounded refusal origin without exception text.

        This private-only failure envelope cannot be mistaken for an approved
        offer receipt; B62 still verifies the original strict success keys.
        """
        required = {"request_ref", "owner_subject_ref", "account_ref", "workspace_ref"}
        # Cloudflare's Python RPC guarantees plain dict for supported objects.
        # Keep strict type and field checks; never trust browser-supplied scope.
        payload = _owner_rpc_payload_dict(payload)
        if payload is None:
            return _owner_rpc_failure("private_payload_type_invalid")
        if set(payload) != required:
            return _owner_rpc_failure("private_keys_invalid")
        if not _ref(payload["request_ref"]):
            return _owner_rpc_failure("private_request_ref_invalid")
        from .pending_pc_link import _canonical_owner_subject_ref
        if not _canonical_owner_subject_ref(payload["owner_subject_ref"]):
            return _owner_rpc_failure("private_owner_subject_invalid")
        for field in ("account_ref", "workspace_ref"):
            value = payload[field]
            if type(value) is not str or _DEVICE.fullmatch(value) is None:
                return _owner_rpc_failure("private_" + field + "_invalid")
        try:
            actor = self._pc_actor(payload["request_ref"])
        except BrokerPendingPcPrivateRefused as exc:
            if exc.args == ("pending_pc_live_socket_missing",):
                return _owner_rpc_failure("live_socket_missing")
            if exc.args == ("pending_pc_rpc_disabled",):
                return _owner_rpc_failure("rpc_disabled")
            if exc.args == ("pending_pc_canonical_storage_unavailable",):
                return _owner_rpc_failure("storage_unavailable")
            return _owner_rpc_failure("actor_unavailable")
        except Exception:
            return _owner_rpc_failure("actor_unavailable")
        try:
            receipt = await actor.reserve_owner_intent_once(**payload)
        except Exception as exc:
            # The canonical SQL ledger has already converted SQL exceptions to
            # fixed ControlPlaneContractError.code values. Never emit its text.
            from .contracts import ControlPlaneContractError
            if type(exc) is ControlPlaneContractError:
                classification = {
                    "pending_pc_owner_scope_invalid": "owner_scope_invalid",
                    "pending_pc_request_unavailable": "request_unavailable",
                    "pending_pc_request_already_used": "already_used",
                    "pending_pc_outbound_channel_unverified": "outbound_channel_unverified",
                    "pending_pc_store_invalid": "store_invalid",
                    "pending_pc_store_unavailable": "store_unavailable",
                }.get(exc.code)
                if classification:
                    return _owner_rpc_failure(classification)
            from .broker_pending_pc_wss import PendingPcWssRefused
            if type(exc) is PendingPcWssRefused and exc.args == ("pending_pc_reserve_denied",):
                return _owner_rpc_failure("actor_refused")
            return _owner_rpc_failure("sql_reservation_unconfirmed")
        if (
            type(receipt) is not dict
            or set(receipt) != {
                "request_ref", "device_id", "expires_at",
                "device_possession_verified", "connected_to_outbound_channel",
                "reserved_once",
            }
            or receipt["request_ref"] != payload["request_ref"]
            or any(receipt.get(key) is not True for key in (
                "device_possession_verified", "connected_to_outbound_channel", "reserved_once"
            ))
        ):
            return _owner_rpc_failure("receipt_invalid")
        return receipt

    async def deliver_pending_pc_link(self, payload: dict) -> dict[str, Any]:
        """No replays: consume Broker one-use CAS before same WSS send."""
        required = {"request_ref", "device_id", "challenge_id", "pairing_code"}
        payload = _owner_rpc_payload_dict(payload)
        if (
            payload is None or set(payload) != required
            or not _ref(payload["request_ref"])
            or type(payload["device_id"]) is not str
            or _DEVICE.fullmatch(payload["device_id"]) is None
            or type(payload["challenge_id"]) is not str
            or _DEVICE.fullmatch(payload["challenge_id"]) is None
            or type(payload["pairing_code"]) is not str
            or _CODE.fullmatch(payload["pairing_code"]) is None
        ):
            raise BrokerPendingPcPrivateRefused("pending_pc_private_fields_invalid")
        actor = self._pc_actor(payload["request_ref"])
        # Consume one-time slot, never store or echo code; duplicate fails.
        self._pending_pc_live().pop(payload["request_ref"], None)
        try:
            await actor.deliver_once(
                request_ref=payload["request_ref"],
                device_id=payload["device_id"],
                challenge_id=payload["challenge_id"],
                pairing_code=payload["pairing_code"],
            )
        except Exception:
            raise BrokerPendingPcPrivateRefused("pending_pc_delivery_unconfirmed") from None
        return {"ok": True, "sent_once": True, "registered": False, "connected": False}



    async def pending_pc_identity_status(self, payload: dict) -> dict:
        from .broker_pending_pc_identity_handoff import identity_pc_status
        return await identity_pc_status(self, _owner_rpc_payload_dict(payload))

    async def claim_pending_pc_identity_proof(self, payload: dict) -> dict:
        from .broker_pending_pc_identity_handoff import claim_identity_pc_proof
        return await claim_identity_pc_proof(self, _owner_rpc_payload_dict(payload))

    async def reserve_native_pc_gateway(self, payload: dict) -> dict:
        from .broker_pending_pc_native_delivery import reserve_native_pc_gateway
        return await reserve_native_pc_gateway(self, _owner_rpc_payload_dict(payload))

    async def authenticate_native_pc_gateway(self, payload: dict) -> dict:
        from .broker_pending_pc_native_delivery import authenticate_native_pc_gateway
        return await authenticate_native_pc_gateway(self, _owner_rpc_payload_dict(payload))

    async def transfer_native_pc_credential_once(self, payload: dict) -> dict:
        from .broker_pending_pc_native_delivery import transfer_native_pc_credential_once
        return await transfer_native_pc_credential_once(self, _owner_rpc_payload_dict(payload))

    async def receive_native_pc_install_ack(self, payload: dict) -> dict:
        from .broker_pending_pc_native_delivery import receive_native_pc_install_ack
        return await receive_native_pc_install_ack(self, _owner_rpc_payload_dict(payload))

    async def authenticate_native_pc_install_ack(self, payload: dict) -> dict:
        from .broker_pending_pc_native_delivery import authenticate_native_pc_install_ack
        return await authenticate_native_pc_install_ack(self, _owner_rpc_payload_dict(payload))

    async def complete_native_pc_enrollment(self, payload: dict) -> dict:
        from .broker_pending_pc_native_delivery import complete_native_pc_enrollment
        return await complete_native_pc_enrollment(self, _owner_rpc_payload_dict(payload))

    async def _pending_pc_wss_fetch(self, request):
        """Native PC upgrade exclusively on this existing canonical Broker DO."""
        from .broker_pending_pc_wss import fetch_broker_pending_pc_wss
        return await fetch_broker_pending_pc_wss(self, request)

    async def webSocketMessage(self, ws, message):
        from .broker_pending_pc_wss import broker_pending_pc_wss_message
        await broker_pending_pc_wss_message(self, ws, message)

    async def webSocketClose(self, ws, code, reason, was_clean):
        del code, reason, was_clean
        from .broker_pending_pc_wss import broker_pending_pc_wss_close
        await broker_pending_pc_wss_close(self, ws)

    async def webSocketError(self, ws, error):
        del error
        from .broker_pending_pc_wss import broker_pending_pc_wss_close
        await broker_pending_pc_wss_close(self, ws)


class CanonicalBrokerPendingPcBindingRPC:
    """Thin private service-binding relay to the EXISTING authority-ref DO.

    This mixin is inherited only by the private WorkerEntrypoint; it does
    not open an HTTP route or claim the browser's signed-owner permission.
    """

    async def reserve_pending_pc_link(self, payload: dict) -> dict:
        return await self._stub().reserve_pending_pc_link(payload)

    async def reserve_pending_pc_owner_intent(self, payload: dict) -> dict:
        try:
            return await self._stub().reserve_pending_pc_owner_intent(payload)
        except Exception:
            # Distinguishes Worker->DO RPC failure from a DO's fixed refusal
            # envelope without exposing framework exception text.
            return _owner_rpc_failure("do_rpc_unavailable")

    async def deliver_pending_pc_link(self, payload: dict) -> dict:
        return await self._stub().deliver_pending_pc_link(payload)

    async def pending_pc_identity_status(self, payload: dict) -> dict:
        return await self._stub().pending_pc_identity_status(payload)

    async def claim_pending_pc_identity_proof(self, payload: dict) -> dict:
        return await self._stub().claim_pending_pc_identity_proof(payload)

    async def reserve_native_pc_gateway(self, payload: dict) -> dict:
        return await self._stub().reserve_native_pc_gateway(payload)

    async def authenticate_native_pc_gateway(self, payload: dict) -> dict:
        return await self._stub().authenticate_native_pc_gateway(payload)

    async def transfer_native_pc_credential_once(self, payload: dict) -> dict:
        return await self._stub().transfer_native_pc_credential_once(payload)

    async def receive_native_pc_install_ack(self, payload: dict) -> dict:
        return await self._stub().receive_native_pc_install_ack(payload)

    async def authenticate_native_pc_install_ack(self, payload: dict) -> dict:
        return await self._stub().authenticate_native_pc_install_ack(payload)

    async def complete_native_pc_enrollment(self, payload: dict) -> dict:
        return await self._stub().complete_native_pc_enrollment(payload)
