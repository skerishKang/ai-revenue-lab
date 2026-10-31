"""Durable account-bound B66 Saved Quote Skill persistence (#3301).

Authority boundary:
- B66 quote-skill.js remains the canonical Saved Quote Skill semantic authority.
- This module does not reimplement QuoteTemplateProfile or QuoteCore semantics.
- It accepts only an already-approved serialized Skill envelope and verifies the
  bounded storage/approval/fingerprint metadata needed to persist it safely.
- Padiem signed auth / Control Plane owns user and tenant identity.
- Caller-supplied ownership fields are not part of the artifact.
- Existing PADIEM_CHAT_DB D1 is reused; no request-time DDL is allowed.

Raw source quotation bytes are never persisted here. The runtime record is the
approved Saved Quote Skill artifact needed for deterministic repeat generation.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

# Default page size for one saved-skill listing. Not a ceiling: a workspace may
# keep more saved skills and keep reading them (#5895-C).
DEFAULT_SAVED_QUOTE_SKILL_LIST = 50
MAX_SKILL_ID_CHARS = 64
MAX_SKILL_NAME_CHARS = 80
MAX_SKILL_JSON_BYTES = 96 * 1024
MAX_WORKSPACE_ID_CHARS = 160
MAX_USER_ID_CHARS = 80
MAX_SKILL_VERSION = 1_000_000

_SKILL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")
_ROW_ID_RE = re.compile(r"^b66skill_[0-9a-f]{32}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_EXPECTED_RENDERER_CONTRACT = "quote-template-renderer.v1"
_EXPECTED_CALCULATION_AUTHORITY = "quote-core"

# #3180 ③: the same table holds one more kind of asset - a form the owner
# already uses, registered from their own PC. It is NOT a certified skill: the
# PC lane fills the owner's workbook and the sheet's own formulas do the
# arithmetic, so this kind never claims QuoteCore authority or the renderer
# contract above.
SKILL_KIND_QUOTE = "skill"
SKILL_KIND_PC_FORM = "pc_form"
SKILL_KINDS = (SKILL_KIND_QUOTE, SKILL_KIND_PC_FORM)
PC_FORM_RENDERER_CONTRACT = "pc-excel-form.v1"
PC_FORM_CALCULATION_AUTHORITY = "excel-formulas"
MAX_FORM_PATH_CHARS = 1024
MAX_FORM_FILENAME_CHARS = 200
MAX_FORM_SHEETS = 8
MAX_FORM_CELLS = 600
MAX_FORM_TEXT_CHARS = 200
MAX_FORM_ITEM_ROWS = 20
MAX_FORM_JSON_BYTES = 48 * 1024


class SavedQuoteSkillStoreError(RuntimeError):
    pass


_FORM_CELL_RE = re.compile(r"^[A-Z]{1,3}[1-9][0-9]{0,6}$")


@dataclass(frozen=True, slots=True)
class ApprovedSavedQuoteSkillArtifact:
    """Storage envelope for one canonical, already-approved B66 Skill."""

    skill_id: str
    skill_name: str
    fingerprint: str
    version: int
    serialized_json: str
    kind: str = SKILL_KIND_QUOTE


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _row_id() -> str:
    return "b66skill_" + uuid.uuid4().hex


def _clean_owner(value: object, *, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise SavedQuoteSkillStoreError(f"{label} is required")
    text = value.strip()
    if not text or len(text) > limit or _CONTROL_RE.search(text):
        raise SavedQuoteSkillStoreError(f"{label} is invalid")
    return text


def _clean_skill_name(value: object) -> str:
    if not isinstance(value, str):
        raise SavedQuoteSkillStoreError("skill_name is invalid")
    text = " ".join(value.split())
    if not text or len(text) > MAX_SKILL_NAME_CHARS or _CONTROL_RE.search(text):
        raise SavedQuoteSkillStoreError("skill_name is invalid")
    return text


def _clean_form_path(value: object) -> str:
    """The PC-side path the read used, kept only as a reference.

    It is either a full PC path or a granted-folder-relative one; both are only
    ever resolved again through the owner's own grants, so a value that escapes
    upward is refused here rather than at the machine.
    """

    if not isinstance(value, str):
        raise SavedQuoteSkillStoreError("form path is invalid")
    text = value.strip().replace("\\", "/")
    if (not text or len(text) > MAX_FORM_PATH_CHARS or _CONTROL_RE.search(text)
            or text.startswith("/") or text.startswith("~")):
        raise SavedQuoteSkillStoreError("form path is invalid")
    segments = text.split("/")
    if any(segment in {"", ".."} for segment in segments):
        raise SavedQuoteSkillStoreError("form path is invalid")
    return text


def _clean_form_filename(value: object) -> str:
    if not isinstance(value, str):
        raise SavedQuoteSkillStoreError("form filename is invalid")
    text = value.strip().replace("\\", "/").rsplit("/", 1)[-1]
    if (not text or len(text) > MAX_FORM_FILENAME_CHARS or _CONTROL_RE.search(text)
            or not text.lower().endswith(".xlsx")):
        raise SavedQuoteSkillStoreError("form filename is invalid")
    return text


def _clean_form_structure(value: object) -> dict[str, Any]:
    """The lane's own description, bounded: sheet names, cells, merges.

    Only what the fill prompt needs — an address, its displayed text and whether
    the cell is a formula — is kept. Values the model wrote are not part of a
    form; they belong to one quote.
    """

    if not isinstance(value, dict) or set(value) != {"sheets"}:
        raise SavedQuoteSkillStoreError("form structure is invalid")
    sheets = value.get("sheets")
    if not isinstance(sheets, list) or not sheets or len(sheets) > MAX_FORM_SHEETS:
        raise SavedQuoteSkillStoreError("form structure is invalid")
    kept: list[dict[str, Any]] = []
    total_cells = 0
    for sheet in sheets:
        if not isinstance(sheet, dict):
            raise SavedQuoteSkillStoreError("form structure is invalid")
        name = sheet.get("name")
        rows = sheet.get("rows")
        columns = sheet.get("columns")
        merged = sheet.get("merged", [])
        cells = sheet.get("cells")
        if (not isinstance(name, str) or not name.strip() or len(name) > 120 or _CONTROL_RE.search(name)
                or isinstance(rows, bool) or not isinstance(rows, int) or not (1 <= rows <= 100000)
                or isinstance(columns, bool) or not isinstance(columns, int) or not (1 <= columns <= 1000)
                or not isinstance(merged, list) or len(merged) > 200
                or not isinstance(cells, list)):
            raise SavedQuoteSkillStoreError("form structure is invalid")
        clean_merged = []
        for item in merged:
            if not isinstance(item, str) or not item or len(item) > 40:
                raise SavedQuoteSkillStoreError("form structure is invalid")
            clean_merged.append(item)
        clean_cells = []
        for cell in cells:
            if not isinstance(cell, dict):
                raise SavedQuoteSkillStoreError("form structure is invalid")
            address = cell.get("cell")
            text = cell.get("text")
            formula = cell.get("formula", False)
            if (not isinstance(address, str) or not _FORM_CELL_RE.fullmatch(address)
                    or not isinstance(text, str) or not isinstance(formula, bool)):
                raise SavedQuoteSkillStoreError("form structure is invalid")
            if total_cells >= MAX_FORM_CELLS:
                raise SavedQuoteSkillStoreError("form structure is too large")
            total_cells += 1
            clean_cells.append({
                "cell": address, "text": text[:MAX_FORM_TEXT_CHARS], "formula": formula,
            })
        kept.append({
            "name": name.strip(), "rows": rows, "columns": columns,
            "merged": clean_merged, "cells": clean_cells,
        })
    return {"sheets": kept}


def _clean_form_item_rows(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > MAX_FORM_ITEM_ROWS:
        raise SavedQuoteSkillStoreError("form item rows are invalid")
    kept = []
    for row in value:
        if not isinstance(row, dict):
            raise SavedQuoteSkillStoreError("form item rows are invalid")
        sheet = row.get("sheet")
        template_row = row.get("template_row")
        at_row = row.get("at_row")
        count = row.get("count")
        if (not isinstance(sheet, str) or not sheet.strip() or len(sheet) > 120
                or any(isinstance(v, bool) or not isinstance(v, int) or not (1 <= v <= 100000)
                       for v in (template_row, at_row, count))):
            raise SavedQuoteSkillStoreError("form item rows are invalid")
        kept.append({"sheet": sheet.strip(), "template_row": template_row,
                     "at_row": at_row, "count": count})
    return kept


def _clean_form(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"path", "filename", "structure", "item_rows"}:
        raise SavedQuoteSkillStoreError("form is invalid")
    form = {
        "path": _clean_form_path(value.get("path")),
        "filename": _clean_form_filename(value.get("filename")),
        "structure": _clean_form_structure(value.get("structure")),
        "item_rows": _clean_form_item_rows(value.get("item_rows")),
    }
    try:
        encoded = json.dumps(form, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise SavedQuoteSkillStoreError("form is invalid") from exc
    if len(encoded) > MAX_FORM_JSON_BYTES:
        raise SavedQuoteSkillStoreError("form is too large")
    return form


def build_pc_form_artifact(
    *,
    skill_id: object,
    skill_name: object,
    form: object,
    approved_at: str,
) -> ApprovedSavedQuoteSkillArtifact:
    """The envelope for one owner-registered PC form, in this same store.

    `approved` here means the owner registered their own form after seeing what
    the fill wrote into it (#6177). No operator certification is implied, and the
    envelope never carries the workbook's bytes: the PC keeps the original and
    the fill re-reads it by the stored path.
    """

    if not isinstance(skill_id, str) or not _SKILL_ID_RE.fullmatch(skill_id.strip()):
        raise SavedQuoteSkillStoreError("skill_id is invalid")
    clean_id = skill_id.strip()
    clean_name = _clean_skill_name(skill_name)
    clean_form = _clean_form(form)
    compact_form = json.dumps(clean_form, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    fingerprint = hashlib.sha256(compact_form.encode("utf-8")).hexdigest()
    payload = {
        "schemaVersion": 1,
        "kind": SKILL_KIND_PC_FORM,
        "id": clean_id,
        "name": clean_name,
        "fingerprint": fingerprint,
        "rendererContract": PC_FORM_RENDERER_CONTRACT,
        "calculationAuthority": PC_FORM_CALCULATION_AUTHORITY,
        "approval": {
            "status": "approved",
            "approvedBy": "owner",
            "skillFingerprint": fingerprint,
            "approvedAt": approved_at,
        },
        "form": clean_form,
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(serialized.encode("utf-8")) > MAX_SKILL_JSON_BYTES:
        raise SavedQuoteSkillStoreError("skill_json is too large")
    return ApprovedSavedQuoteSkillArtifact(
        skill_id=clean_id, skill_name=clean_name, fingerprint=fingerprint,
        version=1, serialized_json=serialized, kind=SKILL_KIND_PC_FORM,
    )


def canonicalize_approved_artifact(
    *,
    skill_id: object,
    skill_name: object,
    fingerprint: object,
    version: object,
    serialized_json: object,
    kind: object = SKILL_KIND_QUOTE,
) -> ApprovedSavedQuoteSkillArtifact:
    """Validate only the persistence envelope around canonical B66 Skill JSON.

    Full Skill/Profile semantics remain owned by quote-skill.js. This function
    proves that the stored JSON is bounded, carries matching approval evidence,
    and matches the supplied id/name/fingerprint/version envelope.
    """

    if not isinstance(skill_id, str) or not _SKILL_ID_RE.fullmatch(skill_id.strip()):
        raise SavedQuoteSkillStoreError("skill_id is invalid")
    clean_id = skill_id.strip()
    clean_name = _clean_skill_name(skill_name)
    if not isinstance(fingerprint, str) or not _FINGERPRINT_RE.fullmatch(fingerprint):
        raise SavedQuoteSkillStoreError("skill_fingerprint is invalid")
    if isinstance(version, bool) or not isinstance(version, int) or not (1 <= version <= MAX_SKILL_VERSION):
        raise SavedQuoteSkillStoreError("skill_version is invalid")
    if not isinstance(serialized_json, str) or not serialized_json:
        raise SavedQuoteSkillStoreError("skill_json is invalid")
    try:
        encoded = serialized_json.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise SavedQuoteSkillStoreError("skill_json is invalid") from exc
    if len(encoded) > MAX_SKILL_JSON_BYTES:
        raise SavedQuoteSkillStoreError("skill_json is too large")
    try:
        payload = json.loads(serialized_json)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SavedQuoteSkillStoreError("skill_json is invalid") from exc
    if not isinstance(payload, dict):
        raise SavedQuoteSkillStoreError("skill_json is invalid")

    approval = payload.get("approval")
    if not isinstance(approval, dict) or approval.get("status") != "approved":
        raise SavedQuoteSkillStoreError("skill is not approved")
    if approval.get("skillFingerprint") != fingerprint:
        raise SavedQuoteSkillStoreError("skill approval fingerprint mismatch")
    if payload.get("fingerprint") != fingerprint:
        raise SavedQuoteSkillStoreError("skill fingerprint mismatch")
    if payload.get("id") != clean_id:
        raise SavedQuoteSkillStoreError("skill id mismatch")
    if payload.get("name") != clean_name:
        raise SavedQuoteSkillStoreError("skill name mismatch")
    if not isinstance(kind, str) or kind not in SKILL_KINDS:
        raise SavedQuoteSkillStoreError("skill kind is invalid")
    if kind == SKILL_KIND_PC_FORM:
        # A PC form never claims the certified renderer or QuoteCore arithmetic:
        # its totals come from the workbook's own formulas.
        if payload.get("kind") != SKILL_KIND_PC_FORM:
            raise SavedQuoteSkillStoreError("pc form kind mismatch")
        if payload.get("rendererContract") != PC_FORM_RENDERER_CONTRACT:
            raise SavedQuoteSkillStoreError("pc form renderer contract mismatch")
        if payload.get("calculationAuthority") != PC_FORM_CALCULATION_AUTHORITY:
            raise SavedQuoteSkillStoreError("pc form calculation authority mismatch")
        if payload.get("approval", {}).get("approvedBy") != "owner":
            raise SavedQuoteSkillStoreError("pc form approval is not the owner's")
        _clean_form(payload.get("form"))
    else:
        if payload.get("kind") not in (None, SKILL_KIND_QUOTE):
            raise SavedQuoteSkillStoreError("skill kind mismatch")
        if payload.get("rendererContract") != _EXPECTED_RENDERER_CONTRACT:
            raise SavedQuoteSkillStoreError("renderer contract mismatch")
        if payload.get("calculationAuthority") != _EXPECTED_CALCULATION_AUTHORITY:
            raise SavedQuoteSkillStoreError("calculation authority mismatch")

    # Persist a compact deterministic JSON projection. The B66 semantic
    # authority already canonicalizes the Skill; storage normalizes whitespace
    # only so byte size and readback are stable.
    compact = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if len(compact.encode("utf-8")) > MAX_SKILL_JSON_BYTES:
        raise SavedQuoteSkillStoreError("skill_json is too large")

    return ApprovedSavedQuoteSkillArtifact(
        skill_id=clean_id,
        skill_name=clean_name,
        fingerprint=fingerprint,
        version=version,
        serialized_json=compact,
        kind=kind,
    )


def validate_row_id(value: object) -> str:
    if not isinstance(value, str) or not _ROW_ID_RE.fullmatch(value.strip()):
        raise SavedQuoteSkillStoreError("saved skill id is invalid")
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


def _public_projection(row: dict[str, Any], *, include_skill: bool) -> dict[str, Any]:
    kind = str(row.get("skill_kind") or SKILL_KIND_QUOTE)
    projected: dict[str, Any] = {
        "saved_skill_id": str(row.get("id", "")),
        "workspace_id": str(row.get("workspace_id", "")),
        "skill_id": str(row.get("skill_id", "")),
        "skill_name": str(row.get("skill_name", "")),
        "skill_fingerprint": str(row.get("skill_fingerprint", "")),
        "skill_version": int(row.get("skill_version", 0)),
        "skill_kind": kind,
        "status": str(row.get("status", "")),
        "created_at": str(row.get("created_at", "")),
        "updated_at": str(row.get("updated_at", "")),
    }
    raw = row.get("skill_json")
    payload: dict[str, Any] | None = None
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
            payload = decoded if isinstance(decoded, dict) else None
        except json.JSONDecodeError:
            payload = None
    if include_skill:
        projected["skill"] = payload
    # A PC form's list entry has to say WHICH form it is without shipping the
    # whole structure to every list read: the owner's own PC path and file name.
    if kind == SKILL_KIND_PC_FORM:
        form = payload.get("form") if payload else None
        form = form if isinstance(form, dict) else {}
        projected["form_path"] = form.get("path") if isinstance(form.get("path"), str) else ""
        projected["form_filename"] = (
            form.get("filename") if isinstance(form.get("filename"), str) else ""
        )
    return projected


class SavedQuoteSkillStore(Protocol):
    async def put_approved_skill(
        self,
        *,
        user_id: str,
        workspace_id: str,
        artifact: ApprovedSavedQuoteSkillArtifact,
    ) -> dict[str, Any]: ...

    async def list_skills(
        self,
        *,
        user_id: str,
        workspace_id: str,
        limit: int = DEFAULT_SAVED_QUOTE_SKILL_LIST,
    ) -> list[dict[str, Any]]: ...

    async def get_skill(
        self,
        *,
        user_id: str,
        workspace_id: str,
        saved_skill_id: str,
    ) -> dict[str, Any] | None: ...

    async def disable_skill(
        self,
        *,
        user_id: str,
        workspace_id: str,
        saved_skill_id: str,
    ) -> bool: ...


class D1SavedQuoteSkillStore:
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

    async def put_approved_skill(
        self,
        *,
        user_id: str,
        workspace_id: str,
        artifact: ApprovedSavedQuoteSkillArtifact,
    ) -> dict[str, Any]:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        if not isinstance(artifact, ApprovedSavedQuoteSkillArtifact):
            raise SavedQuoteSkillStoreError("approved artifact is required")

        existing = await self._first(
            "SELECT id FROM b66_saved_quote_skill "
            "WHERE user_id=? AND workspace_id=? AND skill_id=? AND skill_version=?",
            owner, workspace, artifact.skill_id, artifact.version,
        )
        now = _now_iso()
        if existing and isinstance(existing.get("id"), str):
            row_id = existing["id"]
            await self._run(
                "UPDATE b66_saved_quote_skill "
                "SET skill_name=?, skill_fingerprint=?, skill_json=?, skill_kind=?, "
                "status='approved', updated_at=? "
                "WHERE id=? AND user_id=? AND workspace_id=?",
                artifact.skill_name, artifact.fingerprint, artifact.serialized_json,
                artifact.kind, now, row_id, owner, workspace,
            )
        else:
            row_id = _row_id()
            await self._run(
                # `skill_kind` is appended last so the shape this table has
                # always had (migration 079 adds the column at the end) reads
                # first, exactly as the provisioning gate contract expects.
                "INSERT INTO b66_saved_quote_skill "
                "(id, user_id, workspace_id, skill_id, skill_name, skill_fingerprint, "
                "skill_version, skill_json, status, created_at, updated_at, "
                "skill_kind) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?, ?)",
                row_id, owner, workspace, artifact.skill_id, artifact.skill_name,
                artifact.fingerprint, artifact.version, artifact.serialized_json,
                now, now, artifact.kind,
            )

        row = await self._first(
            "SELECT id, workspace_id, skill_id, skill_name, skill_fingerprint, skill_version, "
            "skill_json, skill_kind, status, created_at, updated_at FROM b66_saved_quote_skill "
            "WHERE id=? AND user_id=? AND workspace_id=?",
            row_id, owner, workspace,
        )
        if not row:
            raise SavedQuoteSkillStoreError("saved quote skill write failed")
        return _public_projection(row, include_skill=True)

    async def list_skills(
        self,
        *,
        user_id: str,
        workspace_id: str,
        limit: int = DEFAULT_SAVED_QUOTE_SKILL_LIST,
    ) -> list[dict[str, Any]]:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        bounded = max(1, int(limit))
        rows = await self._all(
            "SELECT id, workspace_id, skill_id, skill_name, skill_fingerprint, skill_version, "
            "skill_json, skill_kind, status, created_at, updated_at FROM b66_saved_quote_skill "
            "WHERE user_id=? AND workspace_id=? AND status='approved' "
            "ORDER BY updated_at DESC LIMIT ?",
            owner, workspace, bounded,
        )
        return [_public_projection(row, include_skill=False) for row in rows]

    async def get_skill(
        self,
        *,
        user_id: str,
        workspace_id: str,
        saved_skill_id: str,
    ) -> dict[str, Any] | None:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        row_id = validate_row_id(saved_skill_id)
        row = await self._first(
            "SELECT id, workspace_id, skill_id, skill_name, skill_fingerprint, skill_version, "
            "skill_json, skill_kind, status, created_at, updated_at FROM b66_saved_quote_skill "
            "WHERE id=? AND user_id=? AND workspace_id=? AND status='approved'",
            row_id, owner, workspace,
        )
        return _public_projection(row, include_skill=True) if row else None

    async def disable_skill(
        self,
        *,
        user_id: str,
        workspace_id: str,
        saved_skill_id: str,
    ) -> bool:
        owner = _clean_owner(user_id, label="user_id", limit=MAX_USER_ID_CHARS)
        workspace = _clean_owner(workspace_id, label="workspace_id", limit=MAX_WORKSPACE_ID_CHARS)
        row_id = validate_row_id(saved_skill_id)
        existing = await self._first(
            "SELECT id FROM b66_saved_quote_skill "
            "WHERE id=? AND user_id=? AND workspace_id=? AND status='approved'",
            row_id, owner, workspace,
        )
        if not existing:
            return False
        await self._run(
            "UPDATE b66_saved_quote_skill SET status='disabled', updated_at=? "
            "WHERE id=? AND user_id=? AND workspace_id=? AND status='approved'",
            _now_iso(), row_id, owner, workspace,
        )
        return True
