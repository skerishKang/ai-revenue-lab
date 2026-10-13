"""#4139 source-only, SAME Broker DO durable pre-enrollment channel ledger.

This ledger is NOT a second broker, device account, pairing challenge or
production HTTP endpoint. It stores ONLY one nonce, lease correlation and
replay counter alongside the existing canonical Broker pairing authority in
the SAME DO SQLite. Credential and pairing code are never stored here.

Proof possession is derived from the issued pairing code, not an untrusted
device_id, HTTP header, or a new private secret. It identifies a deliberately
authorized enrolment session, NOT the PC's physical hardware or DPAPI store.
A reviewed TLS/443 transport and PC-side sender are mandatory before release.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from typing import Any, Callable

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker_pairing import _ref, _aware
from local_agent_broker_pairing_durable import DurableBrokerPairingAuthority, _rows, _iso

BOOTSTRAP_PRODUCTION_ENABLED = False
BOOTSTRAP_HTTP_ROUTE_MOUNTED = False
BOOTSTRAP_SCHEMA_INSTALLED_BY_DEFAULT = False
BOOTSTRAP_TRANSCRIPT = "padiem.connector-gateway-bootstrap.v1"
BOOTSTRAP_SESSION_TRANSCRIPT = "padiem.connector-gateway-session.v1"
BOOTSTRAP_TTL_SECONDS = 60
MAX_BOOTSTRAP_RECORDS = 4096
_ALLOWED_ACTIONS = frozenset({"credential_fetch", "install_ack", "revoke_verdict"})
_HEX64 = re.compile(r"^[a-f0-9]{64}$")
_LEASE = re.compile(r"^gateway\.[0-9a-f]{32}$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_local_agent_gateway_bootstrap (
 challenge_id TEXT PRIMARY KEY,
 device_id TEXT NOT NULL,
 lease_ref TEXT UNIQUE NOT NULL,
 nonce_hex TEXT NOT NULL,
 challenge_expires_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 verified_at TEXT NULL,
 next_counter INTEGER NOT NULL CHECK (next_counter >= 1 AND next_counter <= 4),
 failed_proofs INTEGER NOT NULL DEFAULT 0 CHECK (failed_proofs BETWEEN 0 AND 3),
 failed_actions INTEGER NOT NULL DEFAULT 0 CHECK (failed_actions BETWEEN 0 AND 3),
 terminal_action TEXT NULL
)
"""


def _err(code: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, "Canonical device bootstrap refused")


def _now(value: datetime) -> datetime:
    return _aware(value, "gateway time")


def _nonce(value: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise _err("gateway_bootstrap_invalid_nonce")
    return value


def _lease(value: str) -> str:
    if not isinstance(value, str) or _LEASE.fullmatch(value) is None:
        raise _err("gateway_bootstrap_invalid_lease")
    return value


def _mac_text(*values: str) -> bytes:
    return "\n".join(values).encode("utf-8")


def bootstrap_mac(*, pairing_code: str, challenge_id: str,
                  device_id: str, nonce_hex: str, lease_ref: str) -> str:
    """PC computes this from the one-use code after seeing server-issued nonce."""
    if not isinstance(pairing_code, str) or re.fullmatch(r"[0-9a-f]{32}", pairing_code) is None:
        raise _err("gateway_bootstrap_invalid_code")
    return hmac.new(pairing_code.encode("ascii"), _mac_text(
        BOOTSTRAP_TRANSCRIPT, challenge_id, device_id,
        _nonce(nonce_hex), _lease(lease_ref),
    ), hashlib.sha256).hexdigest()


def session_mac(*, pairing_code: str, challenge_id: str, device_id: str,
                nonce_hex: str, lease_ref: str, action: str, counter: int,
                payload_sha256: str) -> str:
    """POP MAC on the *canonical server-computed* request body digest.

    Never accept a client-authored body hash as a substitute for hashing the
    exact received HTTPS bytes at the trusted boundary.
    """
    if action not in _ALLOWED_ACTIONS or type(counter) is not int or not 1 <= counter <= 3:
        raise _err("gateway_bootstrap_invalid_action")
    if not isinstance(pairing_code, str) or re.fullmatch(r"[0-9a-f]{32}", pairing_code) is None:
        raise _err("gateway_bootstrap_invalid_code")
    key = hmac.new(pairing_code.encode("ascii"), _mac_text(
        BOOTSTRAP_SESSION_TRANSCRIPT, challenge_id, device_id,
        _nonce(nonce_hex), _lease(lease_ref),
    ), hashlib.sha256).digest()
    return hmac.new(key, _mac_text(
        BOOTSTRAP_SESSION_TRANSCRIPT, action, str(counter), _nonce(payload_sha256),
    ), hashlib.sha256).hexdigest()


def install_gateway_bootstrap_schema(*, storage: Any, migration_id: str,
                                     operator_gate: bool) -> None:
    """Explicit opt-in additive migration on the EXISTING canonical Broker DO."""
    if operator_gate is not True or migration_id != "canonical-broker-gateway-bootstrap-v1":
        raise _err("gateway_bootstrap_schema_disabled")
    def apply() -> None:
        storage.sql.exec(_SCHEMA)
    try:
        storage.transactionSync(apply)
    except Exception as exc:
        raise _err("gateway_bootstrap_store_unavailable") from exc


class DurableBrokerGatewayBootstrap:
    """Nonce → challenge-code MAC → strictly ordered one-shot signed actions.

    The same canonical Broker pairing row is always re-read inside the SAME
    DO transaction, including at finish and every action. An already consumed
    pairing challenge is NEVER eligible for a fresh bootstrap session; after
    canonical redemption the signed delivery/ACK proceeds only via a reserved
    verified lease and the same session MAC, with Broker tracking the binding.
    """

    def __init__(self, *, storage: Any, pairing: DurableBrokerPairingAuthority,
                 nonce_factory: Callable[[], str] | None = None,
                 lease_factory: Callable[[], str] | None = None):
        if not isinstance(pairing, DurableBrokerPairingAuthority):
            raise ValueError("canonical durable Broker pairing authority required")
        if storage is not pairing._storage:
            raise ValueError("gateway ledger MUST use the same Broker DO SQLite")
        if not callable(getattr(storage, "transactionSync", None)):
            raise ValueError("canonical Broker DO transaction required")
        self._storage = storage
        self._pairing = pairing
        self._nonce_factory = nonce_factory or (lambda: secrets.token_hex(32))
        self._lease_factory = lease_factory or (lambda: "gateway." + secrets.token_hex(16))

    def _row(self, challenge_id: str) -> dict[str, Any]:
        items = _rows(self._storage.sql.exec(
            "SELECT * FROM canonical_local_agent_gateway_bootstrap WHERE challenge_id=?",
            challenge_id,
        ))
        if len(items) != 1:
            raise _err("gateway_bootstrap_not_found")
        return items[0]

    def _pending(self, *, challenge_id: str, device_id: str, now: datetime):
        pairing = self._pairing._new_ephemeral()
        p = pairing._pending_challenge(challenge_id)
        if (p.enrollment_binding is None
            or p.enrollment_binding.device_id != device_id
            or p.redeemed_at is not None
            or now >= p.challenge.expires_at):
            raise _err("gateway_bootstrap_challenge_not_pending")
        return pairing, p

    def begin(self, *, challenge_id: str, device_id: str, now: datetime) -> dict[str, Any]:
        challenge_id, device_id, now = _ref(challenge_id, "challenge_id"), _ref(device_id, "device_id"), _now(now)
        nonce_hex = _nonce(self._nonce_factory())
        lease_ref = _lease(self._lease_factory())
        def tx():
            _, p = self._pending(challenge_id=challenge_id, device_id=device_id, now=now)
            # Only expired canonical challenges are purged; a live challenge
            # never receives a second nonce or a second authenticated lease.
            self._storage.sql.exec(
                "DELETE FROM canonical_local_agent_gateway_bootstrap WHERE challenge_expires_at<=?",
                _iso(now),
            )
            count = _rows(self._storage.sql.exec(
                "SELECT COUNT(*) AS n FROM canonical_local_agent_gateway_bootstrap"
            ))[0]["n"]
            if int(count) >= MAX_BOOTSTRAP_RECORDS:
                raise _err("gateway_bootstrap_capacity")
            expiry = min(p.challenge.expires_at, now + timedelta(seconds=BOOTSTRAP_TTL_SECONDS))
            self._storage.sql.exec(
                "INSERT INTO canonical_local_agent_gateway_bootstrap "
                "(challenge_id,device_id,lease_ref,nonce_hex,challenge_expires_at,"
                "expires_at,verified_at,next_counter,terminal_action) "
                "VALUES (?,?,?,?,?,?,NULL,1,NULL)",
                challenge_id, device_id, lease_ref, nonce_hex,
                _iso(p.challenge.expires_at), _iso(expiry),
            )
            return {
                "challenge_id": challenge_id, "device_id": device_id,
                "lease_ref": lease_ref, "nonce_hex": nonce_hex,
                "expires_at": _iso(expiry),
                "credential": False, "challenge_consumed": False,
            }
        try:
            return self._storage.transactionSync(tx)
        except ControlPlaneContractError:
            raise
        except Exception as exc:
            raise _err("gateway_bootstrap_unavailable") from exc

    def finish(self, *, challenge_id: str, device_id: str, lease_ref: str,
               proof_hex: str, now: datetime) -> dict[str, Any]:
        challenge_id, device_id = _ref(challenge_id, "challenge_id"), _ref(device_id, "device_id")
        lease_ref, now = _lease(lease_ref), _now(now)
        if not isinstance(proof_hex, str) or _HEX64.fullmatch(proof_hex) is None:
            raise _err("gateway_bootstrap_invalid_proof")
        def tx():
            pairing, p = self._pending(challenge_id=challenge_id, device_id=device_id, now=now)
            row = self._row(challenge_id)
            if (row["lease_ref"] != lease_ref or row["device_id"] != device_id
                or row["verified_at"] is not None or row["failed_proofs"] >= 3
                or now >= datetime.fromisoformat(
                    row["expires_at"].replace("Z", "+00:00")
                )):
                raise _err("gateway_bootstrap_lease_unavailable")
            code = pairing._pairing_code(
                challenge_id=challenge_id, code_nonce=p.code_nonce,
            )
            expected = bootstrap_mac(
                pairing_code=code, challenge_id=challenge_id,
                device_id=device_id, nonce_hex=row["nonce_hex"], lease_ref=lease_ref,
            )
            if not hmac.compare_digest(expected, proof_hex):
                # Commit the refusal count rather than raising inside a tx,
                # which would roll back the security counter as well.
                self._storage.sql.exec(
                    "UPDATE canonical_local_agent_gateway_bootstrap "
                    "SET failed_proofs=failed_proofs+1 WHERE challenge_id=?",
                    challenge_id,
                )
                return None
            self._storage.sql.exec(
                "UPDATE canonical_local_agent_gateway_bootstrap SET verified_at=? "
                "WHERE challenge_id=? AND verified_at IS NULL", _iso(now), challenge_id,
            )
            return {
                "challenge_id": challenge_id, "device_id": device_id,
                "lease_ref": lease_ref, "verified": True,
                "credential": False, "challenge_consumed": False,
            }
        try:
            result = self._storage.transactionSync(tx)
        except ControlPlaneContractError:
            raise
        except Exception as exc:
            raise _err("gateway_bootstrap_unavailable") from exc
        if result is None:
            raise _err("gateway_bootstrap_proof_invalid")
        return result

    def authorize_action(self, *, challenge_id: str, device_id: str,
                         lease_ref: str, action: str, counter: int,
                         body: bytes, proof_hex: str, now: datetime) -> dict[str, Any]:
        """Authenticate a PC outbound action, advancing its durable replay guard.

        The trusted caller supplies exact received *raw bytes*, not a body hash
        that a device asserts. Cannot be used as an arbitrary Broker RPC; only
        three reviewed message kinds can consume an ordered counter.
        """
        challenge_id, device_id = _ref(challenge_id, "challenge_id"), _ref(device_id, "device_id")
        lease_ref, now = _lease(lease_ref), _now(now)
        if (action not in _ALLOWED_ACTIONS or type(counter) is not int
            or type(body) is not bytes or len(body) > 8192
            or not isinstance(proof_hex, str) or _HEX64.fullmatch(proof_hex) is None):
            raise _err("gateway_bootstrap_invalid_action")
        def tx():
            row = self._row(challenge_id)
            if (row["lease_ref"] != lease_ref or row["device_id"] != device_id
                or row["verified_at"] is None or row["terminal_action"] is not None
                or row["failed_actions"] >= 3
                or now >= datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                or row["next_counter"] != counter):
                raise _err("gateway_bootstrap_action_refused")
            expected_action = {1: "credential_fetch", 2: "install_ack", 3: "revoke_verdict"}.get(counter)
            if action != expected_action:
                raise _err("gateway_bootstrap_action_order_denied")
            pairing = self._pairing._new_ephemeral()
            pending = pairing._pending_challenge(challenge_id)
            if (pending.enrollment_binding is None
                or pending.enrollment_binding.device_id != device_id
                or now >= pending.challenge.expires_at):
                raise _err("gateway_bootstrap_scope_mismatch")
            # Fetch authorizes an outbound request that may trigger the sole
            # canonical redemption. Only the already-consumed Broker challenge
            # can authorize later DPAPI ACK or remote compensation-verdict reads.
            if counter >= 2 and (
                pending.redeemed_at is None
                or pending.redeemed_device_id != device_id
                or pending.redeemed_binding_ref is None
            ):
                raise _err("gateway_bootstrap_unredeemed")
            code = pairing._pairing_code(
                challenge_id=challenge_id, code_nonce=pending.code_nonce,
            )
            expected = session_mac(
                pairing_code=code, challenge_id=challenge_id, device_id=device_id,
                nonce_hex=row["nonce_hex"], lease_ref=lease_ref,
                action=action, counter=counter,
                payload_sha256=hashlib.sha256(body).hexdigest(),
            )
            if not hmac.compare_digest(expected, proof_hex):
                self._storage.sql.exec(
                    "UPDATE canonical_local_agent_gateway_bootstrap "
                    "SET failed_actions=failed_actions+1 WHERE challenge_id=?",
                    challenge_id,
                )
                return None
            self._storage.sql.exec(
                "UPDATE canonical_local_agent_gateway_bootstrap "
                "SET next_counter=?,terminal_action=? WHERE challenge_id=?",
                counter + 1, "revoke_verdict" if counter == 3 else None, challenge_id,
            )
            return {
                "challenge_id": challenge_id, "device_id": device_id,
                "lease_ref": lease_ref, "action": action,
                "counter": counter, "authenticated": True,
            }
        try:
            result = self._storage.transactionSync(tx)
        except ControlPlaneContractError:
            raise
        except Exception as exc:
            raise _err("gateway_bootstrap_unavailable") from exc
        if result is None:
            raise _err("gateway_bootstrap_session_proof_denied")
        return result


__all__ = [
    "BOOTSTRAP_PRODUCTION_ENABLED", "BOOTSTRAP_HTTP_ROUTE_MOUNTED",
    "BOOTSTRAP_SCHEMA_INSTALLED_BY_DEFAULT", "BOOTSTRAP_TTL_SECONDS",
    "BOOTSTRAP_TRANSCRIPT", "BOOTSTRAP_SESSION_TRANSCRIPT",
    "bootstrap_mac", "session_mac", "install_gateway_bootstrap_schema",
    "DurableBrokerGatewayBootstrap",
]
