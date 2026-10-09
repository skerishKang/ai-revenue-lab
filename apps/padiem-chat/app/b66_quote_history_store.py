"""Durable account-bound B66 quotation history — server authority (#3405, Slice A).

Authority boundary:
- Padiem signed auth / Control Plane owns user and tenant identity. This module
  never accepts a caller-supplied owner or workspace.
- A stored record is a *normalized QuoteDraft snapshot*, never a calculation
  authority. Computed totals are stripped before persistence and QuoteCore
  recalculates on load, so a historical total can never override QuoteCore.
- Raw source spreadsheet/PDF bytes, renderer HTML, model/provider payloads and
  credentials are rejected, not stored.
- Existing PADIEM_CHAT_DB D1 is reused; no request-time DDL is allowed.
- Browser-local `quoteBeta.history.v1` is untouched by this module.

Every read/write is scoped by (user_id, workspace_id). A record owned by another
account or workspace is indistinguishable from a missing record: list/get/delete
fail closed without disclosure.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

MAX_QUOTE_HISTORY = 50
MAX_QUOTE_HISTORY_LIMIT = 50
MAX_QUOTE_NO_CHARS = 80
MAX_ISSUE_DATE_CHARS = 40
MAX_SKILL_ID_CHARS = 64
MAX_WORKSPACE_ID_CHARS = 160
MAX_USER_ID_CHARS = 80
MAX_SNAPSHOT_JSON_BYTES = 128 * 1024
MAX_SENDER_JSON_BYTES = 16 * 1024
MAX_ITEMS = 200

_ROW_ID_RE = re.compile(r"^b66quote_[0-9a-f]{32}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_SKILL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Computed totals are never persisted as authority — they are dropped, so a
# stored record cannot carry a total that competes with QuoteCore.
_COMPUTED_TOTAL_KEYS = {
    "subtotal", "sub", "supplyamount", "supply", "vat", "vatamount", "tax",
    "taxamount", "grandtotal", "total", "totals", "amounttotal", "sumtotal",
    "computedtotal", "calculatedtotal",
}
# Non-quotation payloads that must never reach the history store.
_FORBIDDEN_KEY_FRAGMENTS = {
    "xlsx", "xls", "spreadsheet", "pdf", "docx", "hwp", "hwpx",
    "filebytes", "rawbytes", "sourcebytes", "sourcefile", "rawsource",
    "base64", "dataurl", "blob", "binary",
    "rendererhtml", "renderhtml", "html", "stylesheet",
    "model", "modelpayload", "provider", "providerpayload", "prompt", "completion",
    "apikey", "accesstoken", "refreshtoken", "token", "credential", "credentials",
    "password", "secret", "cookie", "authorization", "sessionkey",
}
_SNAPSHOT_ALLOWED_KEYS = {
    "schema", "recipient", "projectname", "quotationno", "quotedate", "issuedate",
    "items", "memo", "notes", "terms", "currency", "vatrate", "taxmode",
    "validitydays", "sender", "savedskillid", "skillfingerprint", "templateprofileid",
    "sourcekind", "language", "locale",
}
_ITEM_ALLOWED_KEYS = {"name", "spec", "unit", "qty", "unitprice", "note"}


class QuoteHistoryStoreError(RuntimeError):
    """Bounded, non-disclosing storage error."""


@dataclass(frozen=True, slots=True)
class NormalizedQuoteDraftSnapshot:
    """A normalized, calculation-authority-free QuoteDraft snapshot."""

    serialized_json: str
    sender_json: str | None
    quote_no: str | None
    issue_date: str | None
    saved_skill_id: str | None
    skill_fingerprint: str | None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _row_id() -> str:
    return "b66quote_" + uuid.uuid4().hex


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _clean_owner(value: object, *, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise QuoteHistoryStoreError(f"{label} is required")
    text = value.strip()
    if not text or len(text) > limit or _CONTROL_RE.search(text):
        raise QuoteHistoryStoreError(f"{label} is invalid")
    return text


def _clean_optional_text(value: object, *, label: str, limit: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise QuoteHistoryStoreError(f"{label} is invalid")
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > limit or _CONTROL_RE.search(text):
        raise QuoteHistoryStoreError(f"{label} is invalid")
    try:
        text.encode("utf-8")
    except UnicodeError as exc:
        raise QuoteHistoryStoreError(f"{label} is invalid") from exc
    return text


def _reject_forbidden_keys(node: object, *, path: str = "snapshot") -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            normalized = _normalized_key(key)
            for fragment in _FORBIDDEN_KEY_FRAGMENTS:
                if fragment in normalized:
                    raise QuoteHistoryStoreError(
                        f"{path}.{key} is not a quotation-history field")
            _reject_forbidden_keys(value, path=f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _reject_forbidden_keys(value, path=f"{path}[{index}]")


def _strip_computed_totals(node: object) -> object:
    """Drop computed-total fields at any depth so none is persisted as authority."""
    if isinstance(node, dict):
        return {key: _strip_computed_totals(value) for key, value in node.items()
                if _normalized_key(key) not in _COMPUTED_TOTAL_KEYS}
    if isinstance(node, list):
        return [_strip_computed_totals(value) for value in node]
    return node


def _normalize_items(items: object) -> list[dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise QuoteHistoryStoreError("snapshot.items is invalid")
    if len(items) > MAX_ITEMS:
        raise QuoteHistoryStoreError("snapshot.items is too large")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise QuoteHistoryStoreError(f"snapshot.items[{index}] is invalid")
        row: dict[str, Any] = {}
        for key, value in item.items():
            if _normalized_key(key) not in _ITEM_ALLOWED_KEYS:
                continue
            if value is None or isinstance(value, (str, int, float, bool)):
                row[str(key)] = value
            else:
                raise QuoteHistoryStoreError(f"snapshot.items[{index}].{key} is invalid")
        normalized.append(row)
    return normalized


def normalize_quote_draft_snapshot(payload: object) -> NormalizedQuoteDraftSnapshot:
    """Validate and normalize a QuoteDraft snapshot for durable storage.

    Unknown top-level fields are dropped; non-quotation payloads are rejected;
    computed totals are removed so QuoteCore remains the only calculation
    authority. The result is deterministic (sorted keys, compact separators).
    """
    if not isinstance(payload, dict):
        raise QuoteHistoryStoreError("snapshot must be an object")
    _reject_forbidden_keys(payload)
    stripped = _strip_computed_totals(payload)
    if not isinstance(stripped, dict):
        raise QuoteHistoryStoreError("snapshot must be an object")

    snapshot: dict[str, Any] = {}
    for key, value in stripped.items():
        if _normalized_key(key) not in _SNAPSHOT_ALLOWED_KEYS:
            continue
        if key == "items" or _normalized_key(key) == "items":
            snapshot["items"] = _normalize_items(value)
            continue
        if value is None or isinstance(value, (str, int, float, bool)):
            snapshot[str(key)] = value
        elif isinstance(value, dict):
            snapshot[str(key)] = {str(k): v for k, v in value.items()
                                  if v is None or isinstance(v, (str, int, float, bool))}
        else:
            raise QuoteHistoryStoreError(f"snapshot.{key} is invalid")

    sender = stripped.get("sender") if isinstance(stripped.get("sender"), dict) else None
    # Python's default json.dumps admits NaN/Infinity and lone Unicode surrogates.
    # Such values can be persisted in D1 and then crash Starlette JSONResponse
    # (allow_nan=False / UTF-8 encoding) on later detail reads.
    try:
        serialized = json.dumps(snapshot, ensure_ascii=False, allow_nan=False,
                                separators=(",", ":"), sort_keys=True)
        snapshot_size = len(serialized.encode("utf-8"))
        sender_json = None
        sender_size = 0
        if sender is not None:
            sender_json = json.dumps(sender, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":"), sort_keys=True)
            sender_size = len(sender_json.encode("utf-8"))
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise QuoteHistoryStoreError("snapshot is not valid JSON for storage") from exc
    if snapshot_size > MAX_SNAPSHOT_JSON_BYTES:
        raise QuoteHistoryStoreError("snapshot is too large")
    if sender_size > MAX_SENDER_JSON_BYTES:
        raise QuoteHistoryStoreError("snapshot.sender is too large")

    saved_skill_id = _clean_optional_text(stripped.get("savedSkillId"),
                                          label="saved_skill_id", limit=MAX_SKILL_ID_CHARS)
    if saved_skill_id is not None and not _SKILL_ID_RE.fullmatch(saved_skill_id):
        raise QuoteHistoryStoreError("saved_skill_id is invalid")
    fingerprint = _clean_optional_text(stripped.get("skillFingerprint"),
                                       label="skill_fingerprint", limit=64)
    if fingerprint is not None and not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise QuoteHistoryStoreError("skill_fingerprint is invalid")

    return NormalizedQuoteDraftSnapshot(
        serialized_json=serialized,
        sender_json=sender_json,
        quote_no=_clean_optional_text(stripped.get("quotationNo") or stripped.get("quoteNo"),
                                      label="quote_no", limit=MAX_QUOTE_NO_CHARS),
        issue_date=_clean_optional_text(stripped.get("issueDate"),
                                        label="issue_date", limit=MAX_ISSUE_DATE_CHARS),
        saved_skill_id=saved_skill_id,
        skill_fingerprint=fingerprint,
    )


def validate_row_id(value: object) -> str:
    if not isinstance(value, str) or not _ROW_ID_RE.fullmatch(value.strip()):
        raise QuoteHistoryStoreError("quote history id is invalid")
    return value.strip()


def _row_to_dict(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    to_py = getattr(row, "to_py", None)
    if callable(to_py):
        converted = to_py()
        if isinstance(converted, dict):
            return dict(converted)
    try:
        return dict(row)
    except (TypeError, ValueError):
        return None


def _rows_from_result(result: Any) -> list[dict[str, Any]]:
    if result is None:
        return []
    rows = getattr(result, "results", None)
    if rows is None and isinstance(result, dict):
        rows = result.get("results")
    if rows is None:
        return []
    output: list[dict[str, Any]] = []
    for row in rows:
        item = _row_to_dict(row)
        if item is not None:
            output.append(item)
    return output


def _read_stored_json_object(raw: object, *, max_bytes: int) -> dict[str, Any]:
    """Refuse an invalid/hostile legacy row before Starlette builds the response.

    Never return NaN/Infinity, a lone UTF-16 surrogate, a non-object snapshot,
    or a malformed/oversized historical JSON blob. These failures must become
    the route's existing bounded 503, not an unhandled Worker HTTP 500.
    """
    if not isinstance(raw, str) or len(raw) > max_bytes:
        raise QuoteHistoryStoreError("stored quote JSON is invalid")
    try:
        if len(raw.encode("utf-8")) > max_bytes:
            raise QuoteHistoryStoreError("stored quote JSON exceeds limit")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise QuoteHistoryStoreError("stored quote JSON must be an object")
        json.dumps(value, allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise QuoteHistoryStoreError("stored quote JSON is invalid") from exc
    return value


def _public_projection(row: dict[str, Any], *, include_snapshot: bool) -> dict[str, Any]:
    """Owner-scoped projection. Totals are never projected as authority."""
    projected: dict[str, Any] = {
        "quote_history_id": str(row.get("id", "")),
        "quote_no": row.get("quote_no"),
        "issue_date": row.get("issue_date"),
        "saved_skill_id": row.get("saved_skill_id"),
        "skill_fingerprint": row.get("skill_fingerprint"),
        "created_at": str(row.get("created_at", "")),
        "updated_at": str(row.get("updated_at", "")),
        # Explicit contract markers: a stored record is not a total authority and
        # QuoteCore must recalculate when the record is reopened.
        "totals_authority": "quote-core",
        "quote_core_recalculation_required": True,
    }
    if include_snapshot:
        projected["snapshot"] = _read_stored_json_object(
            row.get("snapshot_json"), max_bytes=MAX_SNAPSHOT_JSON_BYTES
        )
        sender_raw = row.get("sender_json")
        if sender_raw is not None:
            projected["sender"] = _read_stored_json_object(
                sender_raw, max_bytes=MAX_SENDER_JSON_BYTES
            )
    # A damaged older row can also have malformed text metadata. Catch it
    # inside the store so the route returns a bounded and non-disclosing error.
    try:
        json.dumps(projected, allow_nan=False, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise QuoteHistoryStoreError("stored quote projection is invalid") from exc
    return projected


class QuoteHistoryStore(Protocol):
    async def save_quote(
        self,
        *,
        user_id: str,
        workspace_id: str,
        snapshot: NormalizedQuoteDraftSnapshot,
    ) -> dict[str, Any]: ...

    async def list_quotes(
        self,
        *,
        user_id: str,
        workspace_id: str,
        limit: int = MAX_QUOTE_HISTORY,
    ) -> list[dict[str, Any]]: ...

    async def get_quote(
        self,
        *,
        user_id: str,
        workspace_id: str,
        quote_history_id: str,
    ) -> dict[str, Any] | None: ...

    async def delete_quote(
        self,
        *,
        user_id: str,
        workspace_id: str,
        quote_history_id: str,
    ) -> bool: ...


_SELECT_COLUMNS = (
    "id, quote_no, issue_date, saved_skill_id, skill_fingerprint, "
    "created_at, updated_at"
)


class D1QuoteHistoryStore:
    """Cloudflare D1 adapter using prepared statement binds only."""

    def __init__(self, db: Any):
        if db is None:
            raise ValueError("D1 binding is required")
        self.db = db

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _row_to_dict(await statement.first())

    async def _run(self, sql: str, *values: Any) -> Any:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return await statement.run()

    async def _all(self, sql: str, *values: Any) -> list[dict[str, Any]]:
        statement = self.db.prepare(sql)
        if values:
            statement = statement.bind(*values)
        return _rows_from_result(await statement.run())

    async def save_quote(
        self,
        *,
        user_id: str,
        workspace_id: str,
        snapshot: NormalizedQuoteDraftSnapshot,
    ) -> dict[str, Any]:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        if not isinstance(snapshot, NormalizedQuoteDraftSnapshot):
            raise QuoteHistoryStoreError("normalized snapshot is required")

        row_id = _row_id()
        now = _now_iso()
        await self._run(
            "INSERT INTO b66_quote_history "
            "(id, user_id, workspace_id, quote_no, issue_date, saved_skill_id, "
            "skill_fingerprint, snapshot_json, sender_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row_id, owner, workspace, snapshot.quote_no, snapshot.issue_date,
            snapshot.saved_skill_id, snapshot.skill_fingerprint,
            snapshot.serialized_json, snapshot.sender_json, now, now,
        )
        row = await self._first(
            f"SELECT {_SELECT_COLUMNS} FROM b66_quote_history "
            "WHERE id=? AND user_id=? AND workspace_id=?",
            row_id, owner, workspace,
        )
        if not row:
            raise QuoteHistoryStoreError("quote history write failed")
        return _public_projection(row, include_snapshot=True)

    async def list_quotes(
        self,
        *,
        user_id: str,
        workspace_id: str,
        limit: int = MAX_QUOTE_HISTORY,
    ) -> list[dict[str, Any]]:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        bounded = max(1, min(int(limit), MAX_QUOTE_HISTORY_LIMIT))
        rows = await self._all(
            f"SELECT {_SELECT_COLUMNS} FROM b66_quote_history "
            "WHERE user_id=? AND workspace_id=? "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            owner, workspace, bounded,
        )
        return [_public_projection(row, include_snapshot=False) for row in rows]

    async def get_quote(
        self,
        *,
        user_id: str,
        workspace_id: str,
        quote_history_id: str,
    ) -> dict[str, Any] | None:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        row_id = validate_row_id(quote_history_id)
        row = await self._first(
            f"SELECT {_SELECT_COLUMNS}, snapshot_json, sender_json FROM b66_quote_history "
            "WHERE id=? AND user_id=? AND workspace_id=?",
            row_id, owner, workspace,
        )
        return _public_projection(row, include_snapshot=True) if row else None

    async def delete_quote(
        self,
        *,
        user_id: str,
        workspace_id: str,
        quote_history_id: str,
    ) -> bool:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        row_id = validate_row_id(quote_history_id)
        existing = await self._first(
            "SELECT id FROM b66_quote_history WHERE id=? AND user_id=? AND workspace_id=?",
            row_id, owner, workspace,
        )
        if not existing:
            return False
        await self._run(
            "DELETE FROM b66_quote_history WHERE id=? AND user_id=? AND workspace_id=?",
            row_id, owner, workspace,
        )
        return True


__all__ = [
    "MAX_QUOTE_HISTORY",
    "MAX_QUOTE_HISTORY_LIMIT",
    "D1QuoteHistoryStore",
    "NormalizedQuoteDraftSnapshot",
    "QuoteHistoryStore",
    "QuoteHistoryStoreError",
    "normalize_quote_draft_snapshot",
    "validate_row_id",
]
