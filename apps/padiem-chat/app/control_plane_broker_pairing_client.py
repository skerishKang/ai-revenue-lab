"""Typed async client for the EXISTING private canonical Broker DO Service Binding.

Never create an HTTP fallback or direct public route. The Broker DO returns a
raw device credential exactly once through this private service binding only;
the application host must transfer it to the reviewed Windows protected-store
handoff and must never project/log it to a browser or support record.
"""
from __future__ import annotations

import base64
import binascii
import inspect
import re
from datetime import datetime, timezone
from typing import Any

from .control_plane_identity import IdentityBridgeError

_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_CODE = re.compile(r"^[0-9a-f]{32}$")
_PROOF = re.compile(r"^pairing-proof:[0-9a-f]{64}$")

_CHALLENGE_KEYS = frozenset({
    "challenge_id", "account_ref", "workspace_ref", "issued_at", "expires_at",
    "single_use", "client_time_authority", "raw_pairing_secret",
})
_BINDING_KEYS = frozenset({
    "challenge_id", "consent_ref", "owner_ref", "account_ref", "workspace_ref",
    "device_id", "bound_at", "server_owned_binding", "client_supplied_receipt_trusted",
    "raw_pairing_secret",
})
_ENROLLMENT_KEYS = frozenset({
    "binding_ref", "device_id", "account_ref", "workspace_ref", "credential_ref",
    "credential_generation", "issued_at", "credential_expires_at", "challenge_id",
    "server_owned_binding_refs", "raw_device_credential", "production_ready",
})


def _dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return dict(value)
    conv = getattr(value, "to_py", None)
    if callable(conv):
        value = conv()
        if isinstance(value, dict):
            return dict(value)
    try:
        return dict(value)
    except (TypeError, ValueError):
        return None


def _closed(value: Any, keys: frozenset[str], label: str) -> dict[str, Any]:
    result = _dict(value)
    if result is None or set(result) != keys:
        raise IdentityBridgeError(503, "broker_rpc_invalid", f"{label} schema is invalid.")
    return result


async def _await(value: Any) -> Any:
    return await value if inspect.isawaitable(value) else value


def _safe_owner(value: Any, label: str) -> str:
    if (
        not isinstance(value, str) or not value.strip() or len(value) > 256
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise IdentityBridgeError(503, "broker_rpc_invalid", f"{label} is invalid.")
    return value


def _time(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise IdentityBridgeError(503, "broker_rpc_invalid", f"{name} is invalid.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise IdentityBridgeError(503, "broker_rpc_invalid", f"{name} is invalid.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise IdentityBridgeError(503, "broker_rpc_invalid", f"{name} lacks timezone.")
    return parsed.astimezone(timezone.utc)


def _safe_ref(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _REF.fullmatch(value):
        raise IdentityBridgeError(503, "broker_rpc_invalid", f"{label} is invalid.")
    return value


class CloudflareCanonicalBrokerPairingClient:
    """Private async Service Binding adapter for S1 enrollment only."""

    def __init__(self, binding: Any) -> None:
        if binding is None:
            raise ValueError("canonical Broker Service Binding is required")
        self._binding = binding

    async def _invoke(self, method_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        method = getattr(self._binding, method_name, None)
        if not callable(method):
            raise IdentityBridgeError(503, "canonical_broker_unavailable", "Canonical Broker service is unavailable.")
        try:
            result = _dict(await _await(method(payload)))
        except Exception as exc:
            raise IdentityBridgeError(503, "canonical_broker_unavailable", "Canonical Broker service is unavailable.") from exc
        if result is None or type(result.get("ok")) is not bool:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Canonical Broker service returned invalid data.")
        if result["ok"] is False:
            if set(result) != {"ok", "error"}:
                raise IdentityBridgeError(503, "broker_rpc_invalid", "Canonical Broker error envelope is invalid.")
            err = _dict(result.get("error"))
            if err is None or set(err) != {"code", "message"} or not isinstance(err.get("code"), str):
                raise IdentityBridgeError(503, "broker_rpc_invalid", "Canonical Broker error envelope is invalid.")
            raise IdentityBridgeError(409, err["code"], "Canonical Broker request was refused.")
        return result

    async def gateway_bootstrap_rpc(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Same PRIVATE canonical Broker DO; no public HTTP or alternate owner.

        Accept only the three source-reviewed authenticated device actions.
        Schema installation is an independent, operator-guarded migration and
        must never be reachable through a connected PC WebSocket.
        """
        if type(payload) is not dict or set(payload) != {"operation", "args"}:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Gateway RPC shape invalid.")
        operation, args = payload["operation"], payload["args"]
        required = {
            "begin": {"challenge_id", "device_id", "proof_ref"},
            "finish": {"challenge_id", "device_id", "lease_ref", "proof_hex"},
            "authorize": {
                "challenge_id", "device_id", "lease_ref", "action",
                "counter", "body_b64", "proof_hex",
            },
        }
        if (
            type(operation) is not str or operation not in required
            or type(args) is not dict or set(args) != required[operation]
        ):
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Gateway operation is not allowed.")
        result = await self._invoke("gateway_bootstrap_rpc", payload)
        if set(result) != {"ok", "gateway"} or type(result["gateway"]) is not dict:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Gateway receipt shape invalid.")
        # The full strict receipt, correlation, no-credential and proof checks
        # happen in the one-socket orchestrator before any transfer is begun.
        return result

    async def install_schema(self, *, migration_id: str) -> dict[str, Any]:
        result = await self._invoke("install_pairing_schema", {"migration_id": migration_id})
        if set(result) != {"ok", "schema", "installed_by_default"}:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Pairing schema response shape is invalid.")
        if result.get("schema") != migration_id or result.get("installed_by_default") is not False:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Pairing schema receipt is invalid.")
        return {"schema": result["schema"], "installed_by_default": False}

    async def issue_enrollment_challenge(
        self, *, account_ref: str, workspace_ref: str, consent_ref: str,
        owner_ref: str, device_id: str,
    ) -> tuple[dict[str, Any], str]:
        values = {
            "account_ref": _safe_ref(account_ref, "account_ref"),
            "workspace_ref": _safe_ref(workspace_ref, "workspace_ref"),
            "consent_ref": _safe_ref(consent_ref, "consent_ref"),
            "owner_ref": _safe_owner(owner_ref, "owner_ref"),
            "device_id": _safe_ref(device_id, "device_id"),
        }
        result = await self._invoke("issue_enrollment_challenge", values)
        if set(result) != {"ok", "challenge", "pairing_code"}:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Pairing issue response shape is invalid.")
        challenge = _closed(result.get("challenge"), _CHALLENGE_KEYS, "pairing challenge")
        code = result.get("pairing_code")
        if (
            challenge.get("account_ref") != account_ref
            or challenge.get("workspace_ref") != workspace_ref
            or challenge.get("single_use") is not True
            or challenge.get("client_time_authority") is not False
            or challenge.get("raw_pairing_secret") is not False
            or not isinstance(code, str) or _CODE.fullmatch(code) is None
        ):
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Pairing issue receipt failed correlation.")
        _safe_ref(challenge.get("challenge_id"), "challenge_id")
        expires = _time(challenge.get("expires_at"), "pairing expiry")
        issued = _time(challenge.get("issued_at"), "pairing issuance time")
        if expires <= issued:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Pairing challenge lifetime is invalid.")
        return challenge, code

    async def get_enrollment_binding(
        self, *, challenge_id: str, consent_ref: str | None = None,
        owner_ref: str | None = None, account_ref: str | None = None,
        workspace_ref: str | None = None, device_id: str | None = None,
    ) -> dict[str, Any]:
        expected = {"challenge_id": _safe_ref(challenge_id, "challenge_id")}
        for name, value in (
            ("consent_ref", consent_ref), ("owner_ref", owner_ref),
            ("account_ref", account_ref), ("workspace_ref", workspace_ref), ("device_id", device_id),
        ):
            if value is not None:
                expected[name] = _safe_owner(value, name) if name == "owner_ref" else _safe_ref(value, name)
        result = await self._invoke("get_enrollment_binding", {"challenge_id": challenge_id})
        if set(result) != {"ok", "binding"}:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Enrollment binding response shape is invalid.")
        binding = _closed(result.get("binding"), _BINDING_KEYS, "enrollment binding")
        if (
            any(binding.get(key) != value for key, value in expected.items())
            or binding.get("server_owned_binding") is not True
            or binding.get("client_supplied_receipt_trusted") is not False
            or binding.get("raw_pairing_secret") is not False
        ):
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Enrollment binding failed correlation.")
        _time(binding.get("bound_at"), "enrollment binding time")
        for name in ("consent_ref", "account_ref", "workspace_ref", "device_id"):
            _safe_ref(binding.get(name), name)
        _safe_owner(binding.get("owner_ref"), "owner_ref")
        return binding

    async def verify_enrollment_bootstrap(
        self, *, challenge_id: str, device_id: str, proof_ref: str,
        consent_ref: str, owner_ref: str, account_ref: str, workspace_ref: str,
    ) -> dict[str, Any]:
        """Canonical PRIVATE Broker proof check; never attests the PC by itself."""
        payload = {
            "challenge_id": _safe_ref(challenge_id, "challenge_id"),
            "device_id": _safe_ref(device_id, "device_id"),
            "proof_ref": proof_ref,
            "consent_ref": _safe_ref(consent_ref, "consent_ref"),
            "owner_ref": _safe_owner(owner_ref, "owner_ref"),
            "account_ref": _safe_ref(account_ref, "account_ref"),
            "workspace_ref": _safe_ref(workspace_ref, "workspace_ref"),
        }
        if not isinstance(proof_ref, str) or _PROOF.fullmatch(proof_ref) is None:
            raise IdentityBridgeError(400, "invalid_pairing_proof", "Pairing proof is invalid.")
        result = await self._invoke("verify_enrollment_bootstrap", payload)
        if set(result) != {"ok", "bootstrap"}:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Bootstrap receipt shape invalid.")
        receipt = _closed(
            result.get("bootstrap"),
            frozenset({"challenge_id", "device_id", "proof_valid", "challenge_consumed"}),
            "bootstrap preflight",
        )
        if (
            receipt["challenge_id"] != challenge_id or receipt["device_id"] != device_id
            or receipt["proof_valid"] is not True
            or receipt["challenge_consumed"] is not False
        ):
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Bootstrap proof correlation failed.")
        return receipt

    async def redeem_enrollment(
        self, *, challenge_id: str, device_id: str, proof_ref: str,
        consent_ref: str, owner_ref: str, account_ref: str, workspace_ref: str,
    ) -> tuple[dict[str, Any], bytes]:
        values = {
            "challenge_id": _safe_ref(challenge_id, "challenge_id"),
            "device_id": _safe_ref(device_id, "device_id"),
            "proof_ref": proof_ref,
            "consent_ref": _safe_ref(consent_ref, "consent_ref"),
            "owner_ref": _safe_owner(owner_ref, "owner_ref"),
            "account_ref": _safe_ref(account_ref, "account_ref"),
            "workspace_ref": _safe_ref(workspace_ref, "workspace_ref"),
        }
        if not isinstance(proof_ref, str) or _PROOF.fullmatch(proof_ref) is None:
            raise IdentityBridgeError(400, "invalid_pairing_proof", "Pairing proof is invalid.")
        result = await self._invoke("redeem_enrollment", values)
        expected = {"ok", "enrollment", "credential_b64", "credential_returned_once", "public_http_route"}
        if set(result) != expected:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Enrollment redemption response shape is invalid.")
        enrollment = _closed(result.get("enrollment"), _ENROLLMENT_KEYS, "enrollment receipt")
        if (
            enrollment.get("challenge_id") != challenge_id
            or enrollment.get("device_id") != device_id
            or enrollment.get("account_ref") != account_ref
            or enrollment.get("workspace_ref") != workspace_ref
            or enrollment.get("server_owned_binding_refs") is not True
            or enrollment.get("raw_device_credential") is not False
            or enrollment.get("production_ready") is not False
            or result.get("credential_returned_once") is not True
            or result.get("public_http_route") is not False
        ):
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Enrollment redemption receipt failed correlation.")
        encoded = result.get("credential_b64")
        if not isinstance(encoded, str) or not encoded:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "One-time device credential is missing.")
        try:
            credential = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError, TypeError) as exc:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "One-time device credential encoding is invalid.") from exc
        if not credential or len(credential) > 4096:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "One-time device credential length is invalid.")
        _time(enrollment.get("issued_at"), "enrollment issue time")
        _time(enrollment.get("credential_expires_at"), "device credential expiry")
        return enrollment, credential

    async def owner_device_directory(
        self, *, account_ref: str, workspace_ref: str,
    ) -> dict[str, Any]:
        """Read existing Broker owner-scoped device facts, never credentials.

        This private Service Binding operation is only callable by an OWNER
        session verified at the upper application layer. The account/workspace
        passed here MUST originate from canonical Identity consent, never the PC.
        """
        result = await self._invoke("device_directory", {
            "account_ref": _safe_ref(account_ref, "account_ref"),
            "workspace_ref": _safe_ref(workspace_ref, "workspace_ref"),
        })
        if result.get("available") is False:
            if set(result) != {"ok", "available", "reason"} or result.get("reason") != "no_device_binding":
                raise IdentityBridgeError(503, "broker_rpc_invalid", "Canonical directory unavailable.")
            return {"available": False, "devices": []}
        if (
            set(result) != {"ok", "available", "owner_scoped", "device_count", "max_devices", "devices"}
            or result.get("available") is not True
            or result.get("owner_scoped") is not True
            or type(result.get("devices")) is not list
            or type(result.get("device_count")) is not int
            or type(result.get("max_devices")) is not int
            or not 0 < result["max_devices"] <= 256
            or result["device_count"] != len(result["devices"])
            or result["device_count"] > result["max_devices"]
        ):
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Canonical directory response is invalid.")
        # Do not reinterpret its state, suppress revoked bindings, or invent
        # a server ONLINE fact; the authenticated recovery contract owns the
        # final tightly-scoped projection.
        return {"available": True, "devices": result["devices"]}

    async def revoke_binding(self, *, binding_ref: str) -> dict[str, Any]:
        """Compensate a failed secure credential handoff through the same Broker."""
        binding_ref = _safe_ref(binding_ref, "binding_ref")
        result = await self._invoke("revoke_binding", {
            "binding_ref": binding_ref,
            "now": datetime.now(timezone.utc).isoformat(),
        })
        if set(result) != {"ok", "binding"}:
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Canonical binding revocation shape is invalid.")
        wire = _dict(result.get("binding"))
        if (
            wire is None or wire.get("binding_ref") != binding_ref
            or wire.get("state") != "revoked"
        ):
            raise IdentityBridgeError(503, "broker_rpc_invalid", "Canonical binding revocation was not confirmed.")
        return {"binding_ref": binding_ref, "state": "revoked"}
