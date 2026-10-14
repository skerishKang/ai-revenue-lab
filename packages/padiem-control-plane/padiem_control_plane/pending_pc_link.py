"""#4139 durable one-use pending PC offers on the EXISTING Broker DO SQLite.

Source-only, deliberately not exported as public/private Worker RPC. This is
an atomic replay/capacity/expiry ledger, NOT a proof of hardware identity,
not the outbound socket itself, not Identity consent, and not enrollment.

Only the trusted server-side gateway can create a pending offer after it has
verified an ephemeral PC possession proof on a live outbound TLS channel.
The ledger NEVER decides whether a connection is live from a browser-supplied
boolean: reserve/delivery require a server-injected same-channel verifier.
No code, browser cookie, account/tenant, credential or private key is stored.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
import secrets
from typing import Any, Callable

from padiem_control_plane.contracts import ControlPlaneContractError
def _iso(value: datetime) -> str:
    return _aware(value).isoformat().replace("+00:00", "Z")


def _rows(cursor: Any) -> list[dict[str, Any]]:
    """Same strict DO SqlCursor.toArray contract, without root-only imports."""
    reader = getattr(cursor, "toArray", None)
    if not callable(reader):
        raise _denied("pending_pc_store_unavailable")
    try:
        result = reader()
    except Exception as exc:
        raise _denied("pending_pc_store_unavailable") from exc
    if type(result) is not list or any(type(row) is not dict for row in result):
        raise _denied("pending_pc_store_invalid")
    return result

PENDING_PC_LINK_SCHEMA_INSTALLED_BY_DEFAULT = False
PENDING_PC_LINK_HTTP_ROUTE_MOUNTED = False
PENDING_PC_LINK_PRODUCTION_ENABLED = False
MIGRATION_ID = "canonical-broker-pending-pc-link-v1"
MAX_OFFER_TTL_SECONDS = 90
MAX_UNEXPIRED_OFFERS = 1024

_REF = re.compile(r"^link\.[0-9a-f]{32}$")
_DEVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-]{0,255}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA = """
CREATE TABLE IF NOT EXISTS canonical_broker_pending_pc_link (
 request_ref TEXT PRIMARY KEY,
 device_id TEXT NOT NULL,
 possession_key_sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL,
 expires_at TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','reserved','delivery_claimed')),
 reserved_at TEXT NULL,
 delivery_claimed_at TEXT NULL
)
"""


def _denied(code: str) -> ControlPlaneContractError:
    return ControlPlaneContractError(code, "Pending PC link refused")


def _aware(value: Any) -> datetime:
    if (not isinstance(value, datetime) or value.tzinfo is None
            or value.utcoffset() is None):
        raise _denied("pending_pc_time_invalid")
    return value.astimezone(timezone.utc)


def _time(value: Any) -> datetime:
    if type(value) is not str:
        raise _denied("pending_pc_store_invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _aware(result)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _denied("pending_pc_store_invalid") from exc


@dataclass(frozen=True, slots=True)
class VerifiedPendingPc:
    """Trusted gateway-local admission receipt. Not a user wire object.

    A real outbound gateway MUST authenticate ephemeral key ownership,
    fingerprint the exact attested key and keep the original socket alive.
    This class is not sufficient proof by itself, and is never deserialized
    from HTTP/JSON. The active-channel callback is independently enforced
    at each one-time mutation.
    """

    device_id: str
    possession_key_sha256: str

    def __post_init__(self):
        if (type(self.device_id) is not str or _DEVICE.fullmatch(self.device_id) is None
                or type(self.possession_key_sha256) is not str
                or _FINGERPRINT.fullmatch(self.possession_key_sha256) is None):
            raise _denied("pending_pc_attestation_invalid")


def install_pending_pc_link_schema(
    *, storage: Any, migration_id: str, operator_gate: bool,
) -> None:
    """Never invoked during object construction or production by default."""
    if operator_gate is not True or migration_id != MIGRATION_ID:
        raise _denied("pending_pc_schema_disabled")
    if not callable(getattr(storage, "transactionSync", None)):
        raise _denied("pending_pc_store_unavailable")
    if not callable(getattr(getattr(storage, "sql", None), "exec", None)):
        raise _denied("pending_pc_store_unavailable")
    try:
        storage.transactionSync(lambda: storage.sql.exec(_SCHEMA))
    except Exception as exc:
        raise _denied("pending_pc_store_unavailable") from exc


class DurablePendingPcLink:
    """Source-only atomic offer → reserve → delivery-claim replay barrier.

    Store identity MUST be the canonical Broker DO storage. The caller owns
    authenticating the outbound socket; callbacks must come from that same
    trusted gateway, not a callback supplied by a browser or HTTP request.
    """

    def __init__(
        self, *, storage: Any, canonical_broker_storage: Any,
        channel_verified: Callable[[str, str, str], bool],
        ref_factory: Callable[[], str] | None = None,
    ):
        if storage is not canonical_broker_storage:
            raise ValueError("pending offer must share canonical Broker DO storage")
        if not callable(getattr(storage, "transactionSync", None)):
            raise ValueError("canonical Broker DO transactionSync required")
        if not callable(getattr(getattr(storage, "sql", None), "exec", None)):
            raise ValueError("canonical Broker DO SQLite required")
        if not callable(channel_verified):
            raise ValueError("trusted same-outbound-channel verifier required")
        self._store = storage
        self._verified = channel_verified
        self._ref = ref_factory or (lambda: "link." + secrets.token_hex(16))

    def _tx(self, operation: Callable[[], Any]) -> Any:
        try:
            return self._store.transactionSync(operation)
        except ControlPlaneContractError:
            raise
        except Exception as exc:
            raise _denied("pending_pc_store_unavailable") from exc

    def _live(self, request_ref: str, device_id: str, fingerprint: str) -> None:
        try:
            valid = self._verified(request_ref, device_id, fingerprint)
        except Exception:
            valid = False
        if valid is not True:
            raise _denied("pending_pc_outbound_channel_unverified")

    def _get(self, request_ref: str, *, now: datetime) -> dict[str, Any]:
        if type(request_ref) is not str or _REF.fullmatch(request_ref) is None:
            raise _denied("pending_pc_request_invalid")
        records = _rows(self._store.sql.exec(
            "SELECT * FROM canonical_broker_pending_pc_link WHERE request_ref=?",
            request_ref,
        ))
        if len(records) != 1:
            raise _denied("pending_pc_request_unavailable")
        row = records[0]
        if (row["state"] not in {"pending", "reserved", "delivery_claimed"}
                or _time(row["expires_at"]) <= now):
            raise _denied("pending_pc_request_unavailable")
        if (_DEVICE.fullmatch(row["device_id"]) is None
                or _FINGERPRINT.fullmatch(row["possession_key_sha256"]) is None):
            raise _denied("pending_pc_store_invalid")
        return row

    def offer(
        self, *, attested: VerifiedPendingPc, now: datetime,
        ttl_seconds: int = MAX_OFFER_TTL_SECONDS,
    ) -> dict[str, Any]:
        if type(attested) is not VerifiedPendingPc:
            raise _denied("pending_pc_attestation_required")
        moment = _aware(now)
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= MAX_OFFER_TTL_SECONDS:
            raise _denied("pending_pc_ttl_invalid")
        request_ref = self._ref()
        if type(request_ref) is not str or _REF.fullmatch(request_ref) is None:
            raise _denied("pending_pc_request_invalid")
        expires = moment + timedelta(seconds=ttl_seconds)

        def transaction():
            self._live(request_ref, attested.device_id, attested.possession_key_sha256)
            self._store.sql.exec(
                "DELETE FROM canonical_broker_pending_pc_link WHERE expires_at<=?",
                _iso(moment),
            )
            count = _rows(self._store.sql.exec(
                "SELECT COUNT(*) AS n FROM canonical_broker_pending_pc_link",
            ))[0]["n"]
            if int(count) >= MAX_UNEXPIRED_OFFERS:
                raise _denied("pending_pc_capacity_reached")
            self._store.sql.exec(
                "INSERT INTO canonical_broker_pending_pc_link "
                "(request_ref,device_id,possession_key_sha256,created_at,"
                "expires_at,state,reserved_at,delivery_claimed_at) "
                "VALUES (?,?,?,?,?,'pending',NULL,NULL)",
                request_ref, attested.device_id, attested.possession_key_sha256,
                _iso(moment), _iso(expires),
            )
            return {"request_ref": request_ref, "expires_at": _iso(expires)}
        return self._tx(transaction)

    def reserve_once(self, *, request_ref: str, now: datetime) -> dict[str, Any]:
        """Consume the one approval slot only after live socket verification."""
        moment = _aware(now)

        def transaction():
            row = self._get(request_ref, now=moment)
            if row["state"] != "pending":
                raise _denied("pending_pc_request_already_used")
            self._live(request_ref, row["device_id"], row["possession_key_sha256"])
            self._store.sql.exec(
                "UPDATE canonical_broker_pending_pc_link "
                "SET state='reserved',reserved_at=? "
                "WHERE request_ref=? AND state='pending'",
                _iso(moment), request_ref,
            )
            return {
                "request_ref": request_ref, "device_id": row["device_id"],
                "device_possession_verified": True,
                "connected_to_outbound_channel": True,
                "reserved_once": True, "expires_at": row["expires_at"],
            }
        return self._tx(transaction)

    def claim_delivery_once(
        self, *, request_ref: str, device_id: str, now: datetime,
    ) -> None:
        """One-shot delivery permit; NEVER stores code or retries on send loss."""
        moment = _aware(now)
        if type(device_id) is not str or _DEVICE.fullmatch(device_id) is None:
            raise _denied("pending_pc_device_invalid")

        def transaction():
            row = self._get(request_ref, now=moment)
            if row["state"] != "reserved" or row["device_id"] != device_id:
                raise _denied("pending_pc_delivery_unavailable")
            self._live(request_ref, device_id, row["possession_key_sha256"])
            self._store.sql.exec(
                "UPDATE canonical_broker_pending_pc_link "
                "SET state='delivery_claimed',delivery_claimed_at=? "
                "WHERE request_ref=? AND state='reserved'",
                _iso(moment), request_ref,
            )
        self._tx(transaction)
