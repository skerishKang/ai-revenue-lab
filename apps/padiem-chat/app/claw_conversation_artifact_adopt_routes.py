"""#3933 Hark WEB-FIRST: adopt a completed XLSX result as a NEW web source.

A resolved ``/artifact-followup`` reference is a LOCATOR, never an
authorization. This POST re-verifies the exact owner+conversation+workspace
row that the bounded owner index already proved, re-reads the already-approved
private revision bytes through the SAME trusted workspace document store that
wrote them, re-checks the recorded sha256 and size, and stores them as a NEW
immutable web source document.

The adopted document gets its OWN ``doc_`` identity, so no previous owner
selection, P01 READ decision, workcopy or WRITE receipt can apply to it: the
browser must create a new selection and obtain a NEW P01 READ approval before
any processing starts. This route mints no grant, starts no processing, reads
no model and touches no provider.

The workspace authority is the same owner-bound resolver the publisher used,
so the revision's ``workspace_ref`` and the store tenant always agree; any
mismatch fails closed as ``artifact_not_available``.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import re

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .bounded_request_body import RequestBodyTooLarge, read_bounded_request_body
from .claw_web_xlsx_source_routes import _authority, _error, _NO_STORE
from .history import validate_conversation_id
from .workspace_storage import MAX_WEB_XLSX_BYTES, XLSX_MEDIA_TYPE

ADOPT_PATH = "/api/claw/conversations/{conversation_id}/artifact-followup/adopt"
CONTRACT = "claw-web-xlsx-source-adopt.v1"
_DOC = re.compile(r"doc_[0-9a-f]{32}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MAX_BODY = 512
_XLSX_MAGIC = b"PK\x03\x04"


def _bounded_filename(name: object) -> str | None:
    """Exactly the ``put_web_xlsx`` basename grammar, or None.

    A durable row is never allowed to become a path, a traversal or a
    differently-typed media type; an unusable name refuses the adopt.
    """
    if (type(name) is not str or not 1 <= len(name) <= 155
            or name in (".", "..") or name != name.strip()
            or any(ord(ch) < 32 or ch in '<>:"/\\|?*' for ch in name)
            or not name.lower().endswith(".xlsx")):
        return None
    return name


async def claw_conversation_artifact_adopt(request: Request) -> Response:
    """POST: completed owner artifact -> NEW immutable web XLSX source."""
    authority = await _authority(request)
    if isinstance(authority, Response):
        return authority
    store, owner, workspace = authority
    if request.method != "POST":
        return _error(405, "method_not_allowed")
    try:
        cid = validate_conversation_id(request.path_params.get("conversation_id"))
    except ValueError:
        return _error(400, "invalid_conversation_id")
    if cid is None:
        return _error(400, "invalid_conversation_id")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        return _error(415, "unsupported_media_type")
    try:
        body = await read_bounded_request_body(request, max_bytes=_MAX_BODY)
    except RequestBodyTooLarge:
        return _error(413, "artifact_adopt_request_too_large")
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _error(400, "invalid_json")
    # Exactly the two identifiers the resolved followup projection already
    # carries. No owner, workspace, path, hash or grant is ever accepted.
    if (not isinstance(data, dict) or set(data) != {"artifact_id", "integrity_ref"}
            or type(data["artifact_id"]) is not str
            or not _DOC.fullmatch(data["artifact_id"])
            or type(data["integrity_ref"]) is not str
            or not _HASH.fullmatch(data["integrity_ref"])):
        return _error(400, "invalid_artifact_reference")
    artifact_id = data["artifact_id"]
    integrity_ref = data["integrity_ref"]

    history = getattr(request.app.state, "history_store", None)
    lookup = getattr(history, "get_owner_conversation_artifact", None)
    if not callable(lookup):
        return _error(503, "artifact_index_unavailable")
    try:
        # ONE exact owner+conversation+workspace row bound to a completed run.
        # This is the same bounded index the followup GET proved, re-read
        # rather than trusted from the browser.
        row = lookup(
            user_id=owner, conversation_id=cid,
            workspace_ref=workspace, artifact_id=artifact_id,
        )
        if inspect.isawaitable(row):
            row = await row
    except Exception:
        return _error(503, "artifact_index_read_failed")
    if (not isinstance(row, dict)
            or row.get("artifact_id") != artifact_id
            or row.get("conversation_id") != cid
            or row.get("workspace_ref") != workspace
            or row.get("integrity_ref") != integrity_ref
            or row.get("location_kind") != "r2_bucket"
            or row.get("media_type") != XLSX_MEDIA_TYPE):
        return _error(404, "artifact_not_available")
    size = row.get("size_bytes")
    filename = _bounded_filename(row.get("filename"))
    if (type(size) is not int or not 0 < size <= MAX_WEB_XLSX_BYTES
            or filename is None):
        return _error(409, "artifact_source_unusable")

    try:
        item = await store.get_for_tenant(
            tenant_id=workspace, document_id=artifact_id,
        )
    except Exception:
        return _error(503, "artifact_bytes_unavailable")
    if not isinstance(item, tuple) or len(item) != 2:
        return _error(404, "artifact_bytes_expired")
    metadata, payload = item
    # The durable index hash is the only accepted truth: a substituted,
    # truncated, oversized or non-XLSX object can never become a source.
    if (type(payload) is not bytes or len(payload) != size
            or hashlib.sha256(payload).hexdigest() != integrity_ref
            or payload[:4] != _XLSX_MAGIC
            or getattr(metadata, "document_id", None) != artifact_id
            or getattr(metadata, "tenant_id", None) != workspace):
        return _error(409, "artifact_bytes_mismatch")

    try:
        adopted = await store.put_web_xlsx(
            tenant_id=workspace, owner_id=owner, workspace_id=workspace,
            filename=filename, body=payload,
        )
    except Exception:
        return _error(503, "web_xlsx_adopt_write_unavailable")
    # A NEW immutable identity that is explicitly unauthorized for processing.
    if (not isinstance(adopted, dict)
            or adopted.get("document_id") == artifact_id
            or not _DOC.fullmatch(str(adopted.get("document_id", "")))
            or adopted.get("source_sha256") != integrity_ref
            or adopted.get("size_bytes") != size
            or adopted.get("filename") != filename
            or adopted.get("original_immutable") is not True
            or adopted.get("processing_authorized") is not False):
        return _error(503, "web_xlsx_adopt_projection_invalid")
    return JSONResponse({
        "ok": True,
        "contract_version": CONTRACT,
        "file": adopted,
        "source": "previous_completed_result",
        "adopted_from_artifact_id": artifact_id,
        # Every one of these is structurally true: this route issued no
        # grant, read nothing into a model, started no processing and cannot
        # reuse the previous owner decision for a different document.
        "p01_approval_started": False,
        "processing_started": False,
        "p01_approved": False,
        "drive_uploaded": False,
        "workcopy_created": False,
        "previous_approval_reused": False,
        "read_grant_issued": False,
        "source_material_loaded": False,
        "provider_write_authorized": False,
        "memory_restored": False,
    }, status_code=201, headers=_NO_STORE)
