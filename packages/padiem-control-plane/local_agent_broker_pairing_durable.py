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
import hashlib
from typing import Any, Callable

from padiem_control_plane.contracts import ControlPlaneContractError
from padiem_control_plane.local_agent_broker import BrokerBindingState, InMemoryLocalAgentBrokerAuthority
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


def install_canonical_broker_pairing_schema(
    *, storage: Any, migration_id: str, operator_gate: bool
) -> None:
    """Explicitly install additive pairing tables in existing Broker DO SQLite."""
    if operator_gate is not True or migration_id != "canonical-broker-pairing-v1":
        raise _err("durable_pairing_schema_install_disabled", "explicit reviewed Broker schema gate is off")
    sql = getattr(storage, "sql", None)
    transaction = getattr(storage, "transactionSync", None)
    if not callable(getattr(sql, "exec", None)) or not callable(transaction):
        raise _err("durable_pairing_store_unavailable", "canonical Broker DO storage is unavailable")
    def apply() -> None:
        sql.exec(_CHALLENGE_TABLE)
        sql.exec(_RATE_TABLE)
    try:
        transaction(apply)
    except Exception as exc:
        raise _err("durable_pairing_store_unavailable", "Broker pairing schema install failed") from exc


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
        if not self._migration:
            raise _err("durable_pairing_schema_install_disabled", "explicit reviewed Broker schema gate is off")
        install_canonical_broker_pairing_schema(
            storage=self._storage, migration_id=migration_id, operator_gate=True,
        )

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

    def recovery_verdict(
        self, *, challenge_id: str, device_id: str, consent_ref: str,
        owner_ref: str, account_ref: str, workspace_ref: str,
        binding_ref: str, credential_generation: int,
    ) -> dict[str, Any]:
        """Read ONE consumed challenge and ONE canonical Broker binding atomically.

        The caller MUST first verify a current canonical OWNER session and
        consent. The requested refs are correlation constraints, never grants.
        Original issuance mints generation 1; a subsequent rotation is not
        evidence that the original credential was installed or compensated.
        No retry, issuance, revoke, or credential delivery occurs here.
        """
        def read() -> dict[str, Any]:
            pending = self._new_ephemeral()._pending.get(challenge_id)
            if pending is None or pending.enrollment_binding is None:
                raise _err("recovery_challenge_unavailable")
            original = pending.enrollment_binding
            checks = (
                (original.challenge_id, challenge_id),
                (original.device_id, device_id),
                (original.consent_ref, consent_ref),
                (original.owner_ref, owner_ref),
                (original.account_ref, account_ref),
                (original.workspace_ref, workspace_ref),
            )
            if any(type(a) is not str or type(b) is not str or a != b for a, b in checks):
                raise _err("recovery_scope_mismatch")
            derived = "pairing-binding." + hashlib.sha256(
                f"{challenge_id}:{device_id}".encode("utf-8")
            ).hexdigest()[:32]
            if type(binding_ref) is not str or binding_ref != derived:
                raise _err("recovery_binding_mismatch")
            confirmed = False
            if (
                type(credential_generation) is int and credential_generation == 1
                and pending.redeemed_at is not None
                and pending.redeemed_device_id == device_id
                and pending.redeemed_binding_ref == binding_ref
            ):
                # The same DO SQLite transaction encloses the consumed
                # challenge and the existing canonical Broker CAS snapshot.
                _, broker = self._broker._loaded()
                fact = broker._bindings.get(binding_ref)
                confirmed = (
                    fact is not None
                    and fact.binding_ref == binding_ref
                    and fact.device_id == device_id
                    and fact.account_ref == account_ref
                    and fact.workspace_ref == workspace_ref
                    and type(fact.credential_generation) is int
                    and fact.credential_generation == credential_generation
                    and fact.state is BrokerBindingState.REVOKED
                )
            return {
                "challenge_id": challenge_id, "device_id": device_id,
                "binding_ref": binding_ref,
                "credential_generation": credential_generation,
                "disposition": "revoked" if confirmed else "security_hold",
                "canonical_revocation_confirmed": confirmed,
                "can_retry_challenge": False, "raw_device_credential": False,
            }

        try:
            return self._storage.transactionSync(read)
        except ControlPlaneContractError:
            raise
        except Exception as exc:
            raise _err("durable_pairing_store_unavailable", "recovery authority unavailable") from exc

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

    def verify_enrollment_bootstrap(self, **kwargs: Any) -> dict[str, Any]:
        """Read persisted challenge without rewriting pairing or device rows."""
        def read():
            return self._new_ephemeral().verify_enrollment_bootstrap(**kwargs)
        try:
            return self._storage.transactionSync(read)
        except ControlPlaneContractError:
            raise
        except Exception as exc:
            raise _err("durable_pairing_store_unavailable", "bootstrap verification failed") from exc

    def redeem_enrollment(self, **kwargs: Any):
        return self._call("redeem_enrollment", **kwargs)
