import re
import sqlite3
from datetime import datetime, timezone

from app.db import transaction_scope


class RepositoryError(RuntimeError):
    pass


class DuplicateRecordError(RepositoryError):
    """A UNIQUE constraint was violated (idempotency / no-duplicate guard)."""


class NotFoundError(RepositoryError):
    pass


class InactiveReaderError(RepositoryError):
    pass


class TransactionError(RepositoryError):
    pass


_UTC_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,3})?Z$")


def now_utc_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def validate_timestamp(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not _UTC_ISO_RE.match(value):
        raise RepositoryError(
            f"{field_name} must be UTC ISO-8601 (YYYY-MM-DDTHH:MM:SS[.mmm]Z)"
        )
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise RepositoryError(
                f"{field_name} must be a valid UTC ISO-8601 calendar timestamp"
            ) from exc


__all__ = [
    "RepositoryError",
    "DuplicateRecordError",
    "NotFoundError",
    "InactiveReaderError",
    "TransactionError",
    "now_utc_iso",
    "validate_timestamp",
    "transaction_scope",
]
