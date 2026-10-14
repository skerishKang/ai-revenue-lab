"""Source-only same-native-WSS canonical Broker gateway bootstrap, #4139.

After owner approval the PC starts EXISTING pairing-code possession proof on
the SAME accepted Cloudflare Broker DO websocket. Reuse the canonical Broker
gateway_bootstrap_rpc to do the nonce/lease and signed FINISH checks in its
existing SQLite transaction, NOT a second verifier or credential authority.

Never issue a device credential here. The B54 canonical async Identity host
must separately reauthorize the original owner/consent immediately before
redeem and transfer on the same WSS, with Windows DPAPI ACK verified by the
existing canonical host. Until that private host is available, all subsequent
credential_fetch / install_ack / terminal frames fail closed.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
import re
from typing import Any

_GW_REF = re.compile(r"^gateway\.[0-9a-f]{32}$")
_PROOF = re.compile(r"^pairing-proof:[0-9a-f]{64}$")
_MAC = re.compile(r"^[0-9a-f]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")

CANONICAL_IDENTITY_HOST_ON_NATIVE_WSS_MOUNTED = False
CANONICAL_DPAPI_ACK_PROVEN = False
CANONICAL_BOOTSTRAP_DO_REVIEW_ONLY = True


class CanonicalPcBootstrapDenied(RuntimeError):
    """Never echo signed frames, device credentials or pairing codes."""


def _shape(value: Any, keys: set[str]) -> bool:
    return type(value) is dict and set(value) == keys


def _receipt(reply: Any, keys: set[str]) -> dict[str, Any]:
    if not _shape(reply, {"ok", "gateway"}) or reply["ok"] is not True:
        raise CanonicalPcBootstrapDenied("canonical_gateway_refused")
    value = reply["gateway"]
    if not _shape(value, keys):
        raise CanonicalPcBootstrapDenied("canonical_gateway_receipt_invalid")
    return value


def _expires(value: Any) -> bool:
    if type(value) is not str:
        return False
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return (
            when.tzinfo is not None and when.utcoffset() is not None
            and now < when <= now + timedelta(seconds=60)
        )
    except (ValueError, TypeError, OverflowError):
        return False


class SamePcCanonicalBrokerBootstrap:
    """One existing Broker DO, one connected PC, one approved challenge."""

    def __init__(self, *, broker: Any, device_id: str, challenge_id: str,
                 socket: Any) -> None:
        if (
            not callable(getattr(broker, "gateway_bootstrap_rpc", None))
            or type(device_id) is not str or _REF.fullmatch(device_id) is None
            or type(challenge_id) is not str or _REF.fullmatch(challenge_id) is None
            or not callable(getattr(socket, "send_text", None))
            or getattr(socket, "closed", None) is not False
        ):
            raise CanonicalPcBootstrapDenied("canonical_gateway_unavailable")
        self._broker = broker
        self._device_id = device_id
        self._challenge_id = challenge_id
        self._socket = socket
        self._stage = "begin"
        self._lease: str | None = None

    async def receive(self, frame: dict[str, Any]) -> str:
        """Never returns a success/enrolled claim, including post-FINISH."""
        if getattr(self._socket, "closed", None) is not False:
            raise CanonicalPcBootstrapDenied("canonical_socket_closed")
        if self._stage == "begin":
            if (
                not _shape(frame, {"type", "challenge_id", "device_id", "proof_ref"})
                or frame["type"] != "begin"
                or frame["challenge_id"] != self._challenge_id
                or frame["device_id"] != self._device_id
                or type(frame["proof_ref"]) is not str
                or _PROOF.fullmatch(frame["proof_ref"]) is None
            ):
                raise CanonicalPcBootstrapDenied("canonical_begin_invalid")
            self._stage = "pending_begin"
            try:
                reply = await self._broker.gateway_bootstrap_rpc({
                    "operation": "begin",
                    "args": {
                        "challenge_id": self._challenge_id,
                        "device_id": self._device_id,
                        "proof_ref": frame["proof_ref"],
                    },
                })
                receipt = _receipt(reply, {
                    "challenge_id", "device_id", "lease_ref", "nonce_hex",
                    "expires_at", "credential", "challenge_consumed",
                })
                if (
                    receipt["challenge_id"] != self._challenge_id
                    or receipt["device_id"] != self._device_id
                    or type(receipt["lease_ref"]) is not str
                    or _GW_REF.fullmatch(receipt["lease_ref"]) is None
                    or type(receipt["nonce_hex"]) is not str
                    or _MAC.fullmatch(receipt["nonce_hex"]) is None
                    or receipt["credential"] is not False
                    or receipt["challenge_consumed"] is not False
                    or not _expires(receipt["expires_at"])
                ):
                    raise CanonicalPcBootstrapDenied("canonical_begin_receipt_invalid")
                self._lease = receipt["lease_ref"]
                self._stage = "finish"
                await self._socket.send_text(json.dumps({
                    "type": "nonce", "challenge_id": self._challenge_id,
                    "device_id": self._device_id,
                    "lease_ref": self._lease, "nonce_hex": receipt["nonce_hex"],
                    "expires_at": receipt["expires_at"],
                }, separators=(",", ":"), sort_keys=True))
                return "awaiting_pairing_proof"
            except Exception:
                self._stage = "denied"
                raise CanonicalPcBootstrapDenied("canonical_begin_unconfirmed") from None
        if self._stage == "finish":
            if (
                not _shape(frame, {"type", "lease_ref", "proof_hex"})
                or frame["type"] != "finish"
                or frame["lease_ref"] != self._lease
                or type(frame["proof_hex"]) is not str
                or _MAC.fullmatch(frame["proof_hex"]) is None
            ):
                self._stage = "denied"
                raise CanonicalPcBootstrapDenied("canonical_finish_invalid")
            self._stage = "pending_finish"
            try:
                reply = await self._broker.gateway_bootstrap_rpc({
                    "operation": "finish",
                    "args": {
                        "challenge_id": self._challenge_id,
                        "device_id": self._device_id,
                        "lease_ref": self._lease,
                        "proof_hex": frame["proof_hex"],
                    },
                })
                receipt = _receipt(reply, {
                    "challenge_id", "device_id", "lease_ref", "verified",
                    "credential", "challenge_consumed",
                })
                if (
                    receipt["challenge_id"] != self._challenge_id
                    or receipt["device_id"] != self._device_id
                    or receipt["lease_ref"] != self._lease
                    or receipt["verified"] is not True
                    or receipt["credential"] is not False
                    or receipt["challenge_consumed"] is not False
                ):
                    raise CanonicalPcBootstrapDenied("canonical_finish_receipt_invalid")
                # B54 Identity canonical redeem + real DPAPI ACK MUST run
                # next. This DO has no Identity authorization host. Never
                # grant credential_fetch or report paired_offline here.
                self._stage = "host_required"
                await self._socket.send_text(json.dumps({
                    "type": "bootstrap_verified", "lease_ref": self._lease,
                    "credential": False,
                }, separators=(",", ":"), sort_keys=True))
                return "awaiting_canonical_identity_host"
            except Exception:
                self._stage = "denied"
                raise CanonicalPcBootstrapDenied("canonical_finish_unconfirmed") from None
        self._stage = "denied"
        raise CanonicalPcBootstrapDenied("canonical_identity_host_required")
