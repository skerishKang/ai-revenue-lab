"""Durable pairing challenge adapter on the EXISTING canonical Broker DO SQLite.

The existing Broker DO persists binding/session/command state, but S1 pairing
challenge + consent binding lived in InMemoryBrokerPairingAuthority. This
adapter persists those pending/consumed challenge records and bounded issuance
counters in the SAME Broker Durable Object SQLite storage. It creates no second
Broker, no second database and no raw pairing/credential storage.

Schema installation is an explicit private migration step. The constructor
never installs schema. Production use requires a caller that wraps the complete
operation in the canonical Broker DO transaction and authorizes the private RPC.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import InMemoryLocalAgentBrokerAuthority
from padiem_control_plane.local_agent_broker_pairing import (
    MAX_PAIRING_ISSUANCE_RATE_LIMIT,
    MIN_PAIRING_ISSUANCE_RATE_LIMIT,
    BrokerPairingChallenge,
    BrokerPairingEnrollmentBinding,
    InMemoryBrokerPairingAuthority,
    _PendingBrokerPairingChallenge,
)
from padiem_control_plane.local_agent_broker_state import StateBackedLocalAgentBrokerAuthority

PAIRING_SCHEMA_INSTALLED_BY_DEFAULT = False
PAIRING_PUBLIC_ROUTE_CONFIGURED = False
PAIRING_PRODUCTION_ACTIVATED = False

_CHALLENGE_TABLE = """
CREATE TABLE IF NOT EXISTS canonical_local_agent_pairing_challenge (
 challenge_id TEXT PRIMARY KEY,
 code_nonce TEXT NOT NULL,
 account_ref TEXT NOT NULL,
 workspace_ref TEXT NOT NULL,
 issued_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 redeemed_at TEXT NULL,
 redeemed_device_id TEXT NULL,
 redeemed_binding_ref TEXT NULL,
 consent_ref TEXT NULL,
 owner_ref TEXT NULL,
 enrollment_device_id TEXT NULL,
 bound_at TEXT NULL
)
"""
_RATE_TABLE = """
CREATE TABLE IF NOT EXISTS canonical_local_agent_pairing_rate (
 account_ref TEXT NOT NULL,
 workspace_ref TEXT NOT NULL,
 window_started_at TEXT NOT NULL,
 issued_count INTEGER NOT NULL CHECK (issued_count >= 0),
 PRIMARY KEY(account_ref, workspace_ref)
)
"""


def _err(code: str, message: str | None = None) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, message or code)


def _iso(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _err("invalid_pairing_timestamp", "pairing timestamp must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _dt(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise _err("durable_pairing_state_corrupt", "stored pairing time is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise _err("durable_pairing_state_corrupt", "stored pairing time is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _err("durable_pairing_state_corrupt", "stored pairing time has no timezone")
    return parsed.astimezone(timezone.utc)


def _rows(cursor: Any) -> list[dict[str, Any]]:
    reader = getattr(cursor, "toArray", None)
    if not callable(reader):
        raise _err("durable_pairing_store_unavailable", "canonical Broker SQL cursor is invalid")
    try:
        result = reader()
    except Exception as exc:
        raise _err("durable_pairing_store_unavailable", "canonical Broker SQL query failed") from exc
    if not isinstance(result, list) or any(type(x) is not dict for x in result):
        raise _err("durable_pairing_state_corrupt", "canonical Broker SQL result is invalid")
    return result


class DurableBrokerPairingAuthority:
    """BrokerPairingAuthorityPort persisted in the existing Broker Durable Object.

    Callers must invoke mutations inside this object’s transaction_sync so the
    pairing ledger and the existing canonical Broker binding CAS commit together.
    Do not expose this Python class as a public HTTP route.
    """

    def __init__(
        self,
        *,
        storage: Any,
        broker: StateBackedLocalAgentBrokerAuthority,
        pepper: bytes,
        issuance_rate_limit: int,
        schema_migration_enabled: bool = False,
        code_nonce_factory: Callable[[], str] | None = None,
        credential_factory: Callable[[], bytes] | None = None,
    ) -> None:
        sql = getattr(storage, "sql", None)
        if not callable(getattr(sql, "exec", None)):
            raise ValueError("existing canonical Broker DO SQLite storage required")
        if not callable(getattr(storage, "transactionSync", None)):
            raise ValueError("canonical Broker DO transactionSync required")
        if not isinstance(broker, StateBackedLocalAgentBrokerAuthority):
            raise ValueError("existing StateBackedLocalAgentBrokerAuthority required")
        if type(issuance_rate_limit) is not int or not (
            MIN_PAIRING_ISSUANCE_RATE_LIMIT <= issuance_rate_limit <= MAX_PAIRING_ISSUANCE_RATE_LIMIT
        ):
            raise ValueError("an explicit bounded pairing issuance limit is required")
        if type(schema_migration_enabled) is not bool:
            raise ValueError("schema migration gate must be a strict boolean")
        if not isinstance(pepper, bytes) or len(pepper) < 16:
            raise ValueError("canonical pairing pepper is required")
        self._storage = storage
        self._sql = sql
        self._broker = broker
        self._pepper = pepper
        self._rate = issuance_rate_limit
        self._migration = schema_migration_enabled
        self._nonce_factory = code_nonce_factory
        self._credential_factory = credential_factory

    def install_schema(self, *, migration_id: str) -> None:
        if not self._migration or migration_id != "canonical-broker-pairing-v1":
            raise _err("durable_pairing_schema_install_disabled", "explicit reviewed Broker schema gate is off")
        def apply() -> None:
            self._sql.exec(_CHALLENGE_TABLE)
            self._sql.exec(_RATE_TABLE)
        try:
            self._storage.transactionSync(apply)
        except Exception as exc:
            raise _err("durable_pairing_store_unavailable", "Broker pairing schema install failed") from exc

    def _new_ephemeral(self) -> InMemoryBrokerPairingAuthority:
        # The ephemeral contract object performs the established HMAC,
        # proof-validation and scoped redemption logic; only its dictionaries
        # are restored from and committed to the canonical durable SQL rows.
        authority = InMemoryBrokerPairingAuthority(
            pepper=self._pepper,
            authority=self._broker,
            issuance_rate_limit=self._rate,
            code_nonce_factory=self._nonce_factory,
            credential_factory=self._credential_factory,
        )
        challenges = _rows(self._sql.exec("SELECT * FROM canonical_local_agent_pairing_challenge"))
        for row in challenges:
            challenge_id = row.get("challenge_id")
            nonce = row.get("code_nonce")
            if not isinstance(challenge_id, str) or not isinstance(nonce, str) or challenge_id != "pairing." + nonce:
                raise _err("durable_pairing_state_corrupt", "challenge identity is invalid")
            challenge = BrokerPairingChallenge(
                challenge_id=challenge_id,
                account_ref=row["account_ref"],
                workspace_ref=row["workspace_ref"],
                issued_at=_dt(row["issued_at"]),
                expires_at=_dt(row["expires_at"]),
            )
            binding = None
            enrollment_values = (row.get("consent_ref"), row.get("owner_ref"), row.get("enrollment_device_id"), row.get("bound_at"))
            if any(x is not None for x in enrollment_values):
                if any(x is None for x in enrollment_values):
                    raise _err("durable_pairing_state_corrupt", "partial enrollment binding is invalid")
                binding = BrokerPairingEnrollmentBinding(
                    challenge_id=challenge_id,
                    consent_ref=row["consent_ref"],
                    owner_ref=row["owner_ref"],
                    account_ref=challenge.account_ref,
                    workspace_ref=challenge.workspace_ref,
                    device_id=row["enrollment_device_id"],
                    bound_at=_dt(row["bound_at"]),
                )
            redeemed_at = _dt(row["redeemed_at"]) if row.get("redeemed_at") is not None else None
            redeemed_device_id = row.get("redeemed_device_id")
            redeemed_binding_ref = row.get("redeemed_binding_ref")
            if (redeemed_at is None) != (redeemed_device_id is None) or (redeemed_at is None) != (redeemed_binding_ref is None):
                raise _err("durable_pairing_state_corrupt", "challenge consumption record is incomplete")
            authority._pending[challenge_id] = _PendingBrokerPairingChallenge(
                challenge=challenge,
                code_nonce=nonce,
                redeemed_at=redeemed_at,
                redeemed_device_id=redeemed_device_id,
                redeemed_binding_ref=redeemed_binding_ref,
                enrollment_binding=binding,
            )
        counters = _rows(self._sql.exec("SELECT * FROM canonical_local_agent_pairing_rate"))
        for row in counters:
            authority._issuance_counters[(row["account_ref"], row["workspace_ref"])] = (
                _dt(row["window_started_at"]), int(row["issued_count"])
            )
        return authority

    def _save(self, authority: InMemoryBrokerPairingAuthority) -> None:
        self._sql.exec("DELETE FROM canonical_local_agent_pairing_challenge")
        for challenge_id, pending in authority._pending.items():
            binding = pending.enrollment_binding
            self._sql.exec(
                "INSERT INTO canonical_local_agent_pairing_challenge "
                "(challenge_id,code_nonce,account_ref,workspace_ref,issued_at,expires_at,"
                "redeemed_at,redeemed_device_id,redeemed_binding_ref,consent_ref,owner_ref,"
                "enrollment_device_id,bound_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                challenge_id, pending.code_nonce,
                pending.challenge.account_ref, pending.challenge.workspace_ref,
                _iso(pending.challenge.issued_at), _iso(pending.challenge.expires_at),
                _iso(pending.redeemed_at) if pending.redeemed_at is not None else None,
                pending.redeemed_device_id, pending.redeemed_binding_ref,
                binding.consent_ref if binding is not None else None,
                binding.owner_ref if binding is not None else None,
                binding.device_id if binding is not None else None,
                _iso(binding.bound_at) if binding is not None else None,
            )
        self._sql.exec("DELETE FROM canonical_local_agent_pairing_rate")
        for (account_ref, workspace_ref), (window_started, issued) in authority._issuance_counters.items():
            self._sql.exec(
                "INSERT INTO canonical_local_agent_pairing_rate "
                "(account_ref,workspace_ref,window_started_at,issued_count) VALUES (?,?,?,?)",
                account_ref, workspace_ref, _iso(window_started), issued,
            )

    def _call(self, name: str, **kwargs: Any) -> Any:
        def operation():
            authority = self._new_ephemeral()
            result = getattr(authority, name)(**kwargs)
            self._save(authority)
            return result
        try:
            return self._storage.transactionSync(operation)
        except ControlPlaneContractError:
            raise
        except Exception as exc:
            raise _err("durable_pairing_store_unavailable", "canonical Broker pairing transaction failed") from exc

    def issue_challenge(self, **kwargs: Any):
        return self._call("issue_challenge", **kwargs)

    def redeem(self, **kwargs: Any):
        return self._call("redeem", **kwargs)

    def issue_enrollment_challenge(self, **kwargs: Any):
        return self._call("issue_enrollment_challenge", **kwargs)

    def enrollment_binding(self, **kwargs: Any):
        return self._call("enrollment_binding", **kwargs)

    def redeem_enrollment(self, **kwargs: Any):
        return self._call("redeem_enrollment", **kwargs)
