"""Pure contract for the COM2 backup transfer Worker.

This module never imports the ``workers`` runtime, so every route, name,
checksum and manifest rule is testable on plain CPython. ``worker.py`` is the
thin Workers adapter.

Scope of this slice
-------------------
* Upload a bounded COM2 backup archive plus its manifest to a **private** R2
  bucket.
* Recompute the stored archive checksum and compare it with the manifest
  (``POST .../verify``).
* Download both objects so the operator can run a restore check locally.
* Never delete, never overwrite different bytes, and never decide a retention
  or cost policy.

Reused precedent
----------------
The no-overwrite / sha256 manifest mechanics follow
``ops/padiem-r2-c14-upload-manifest.json`` and
``.github/workflows/padiem-r2-c14-media-upload.yml``. No generic backup
implementation existed in this repository before this slice, so nothing is
duplicated; the R2 access helpers mirror the existing workspace storage code.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

CONTRACT_VERSION = "PADIEM_COM2_BACKUP_V1"
MANIFEST_KIND = "PADIEM_COM2_BACKUP_MANIFEST_V1"

#: Fail-closed deployment gate. Only the literal string ``"true"`` enables the
#: Worker; the committed wrangler config keeps it ``"false"``.
ENABLED_BINDING = "COM2_BACKUP_ENABLED"
BUCKET_BINDING = "COM2_BACKUP_BUCKET"
TOKEN_BINDING = "COM2_BACKUP_WRITE_TOKEN"

ROUTE_PREFIX = "/internal/v1/com2-backup"
CAPABILITIES_ROUTE = ROUTE_PREFIX + "/capabilities"

#: Transfer bound, not a retention or pricing decision. A larger backup needs a
#: reviewed streaming/multipart slice; this Worker buffers the body to compute
#: and verify its checksum.
MAX_PAYLOAD_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_MANIFEST_FILES = 20000

ARTIFACT_PAYLOAD = "payload"
ARTIFACT_MANIFEST = "manifest"
ARTIFACT_VERIFY = "verify"

ARTIFACT_ACTIONS = (ARTIFACT_PAYLOAD, ARTIFACT_MANIFEST, ARTIFACT_VERIFY)
_OBJECT_NAMES = {
    ARTIFACT_PAYLOAD: "payload.tar.gz",
    ARTIFACT_MANIFEST: "manifest.json",
}

_MACHINE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,31}$")
_BACKUP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

MANIFEST_KEYS = frozenset(
    {
        "kind",
        "contract_version",
        "machine",
        "backup_id",
        "created_at",
        "payload_file",
        "payload_bytes",
        "payload_sha256",
        "file_count",
        "total_bytes",
        "files",
        "exclusions",
    }
)
FILE_KEYS = frozenset({"path", "bytes", "sha256"})

STATUS_BY_CODE = {
    "backup_disabled": 503,
    "backup_token_unavailable": 503,
    "backup_storage_unavailable": 503,
    "storage_binding_missing": 503,
    "storage_method_missing": 503,
    "storage_read_failed": 502,
    "storage_body_failed": 502,
    "storage_write_failed": 502,
    "backup_unauthorized": 401,
    "method_not_allowed": 405,
    "not_found": 404,
    "invalid_machine": 400,
    "invalid_backup_id": 400,
    "invalid_checksum": 400,
    "invalid_content_length": 400,
    "invalid_body": 400,
    "invalid_manifest": 400,
    "empty_payload": 400,
    "checksum_mismatch": 400,
    "request_too_large": 413,
    "unsupported_media_type": 415,
    "payload_not_found": 404,
    "manifest_not_found": 404,
    "backup_conflict_no_overwrite": 409,
    "integrity_mismatch": 409,
    "backup_write_unverified": 502,
    "stored_object_too_large": 502,
}


class BackupError(Exception):
    """A bounded, non-secret error code with its HTTP status."""

    def __init__(self, code: str, status: int | None = None):
        super().__init__(code)
        self.code = code
        self.status = status if status is not None else STATUS_BY_CODE.get(code, 400)


@dataclass(frozen=True)
class BackupRoute:
    """A parsed route. ``machine``/``backup_id`` are ``None`` only for capabilities."""

    action: str
    machine: str | None = None
    backup_id: str | None = None


def status_for_code(code: str) -> int:
    return STATUS_BY_CODE.get(code, 400)


def normalize_method(value: object) -> str:
    """The Workers runtime exposes ``http.HTTPMethod``; ``.name`` is stable."""
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.upper()
    return str(value).upper()


def route_path(url: object) -> str:
    if not isinstance(url, str):
        url = str(url)
    try:
        return urlsplit(url).path
    except Exception:
        return ""


def validate_machine(value: object) -> str:
    if not isinstance(value, str) or not _MACHINE_RE.fullmatch(value):
        raise BackupError("invalid_machine", 400)
    return value


def validate_backup_id(value: object) -> str:
    if not isinstance(value, str) or not _BACKUP_ID_RE.fullmatch(value):
        raise BackupError("invalid_backup_id", 400)
    if ".." in value or value in {".", ".."}:
        raise BackupError("invalid_backup_id", 400)
    return value


def validate_sha256(value: object) -> str:
    if not isinstance(value, str):
        raise BackupError("invalid_checksum", 400)
    candidate = value.strip().lower()
    if not _SHA256_RE.fullmatch(candidate):
        raise BackupError("invalid_checksum", 400)
    return candidate


def _manifest_digest(value: object) -> str:
    """A bad digest inside a manifest is a manifest error, not a header error."""
    try:
        return validate_sha256(value)
    except BackupError:
        raise BackupError("invalid_manifest", 400)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def object_key(machine: str, backup_id: str, artifact: str) -> str:
    """Deterministic R2 key. Segment validation happens before this call."""
    try:
        name = _OBJECT_NAMES[artifact]
    except KeyError:
        raise BackupError("not_found", 404)
    return f"com2-backup/v1/{machine}/{backup_id}/{name}"


def parse_route(url: object) -> BackupRoute | None:
    """Return the matched route, or ``None`` for an unknown path.

    A path that is under the prefix but carries an invalid machine, backup id or
    artifact action raises the bounded error instead of quietly becoming 404.
    """
    path = route_path(url)
    if path == CAPABILITIES_ROUTE:
        return BackupRoute("capabilities")
    if not path.startswith(ROUTE_PREFIX + "/"):
        return None
    rest = path[len(ROUTE_PREFIX) + 1 :]
    segments = rest.split("/")
    if len(segments) != 3:
        return None
    machine, backup_id, action = segments[0], segments[1], segments[2]
    if action not in ARTIFACT_ACTIONS:
        return None
    return BackupRoute(
        action=action,
        machine=validate_machine(machine),
        backup_id=validate_backup_id(backup_id),
    )


def parse_bearer(header: object) -> str | None:
    """Extract a bearer value; malformed or missing headers yield ``None``."""
    if not isinstance(header, str):
        return None
    scheme, _, value = header.partition(" ")
    if scheme.strip().lower() != "bearer":
        return None
    token = value.strip()
    if not token or any(ch.isspace() for ch in token):
        return None
    return token


def token_matches(provided: str, expected: str) -> bool:
    """Constant-time comparison; an empty expected token never matches."""
    if not isinstance(provided, str) or not isinstance(expected, str):
        return False
    if not provided or not expected:
        return False
    return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))


def gate_is_open(flag: object) -> bool:
    """Only the literal string ``"true"`` opens the Worker."""
    return isinstance(flag, str) and flag == "true"


def declared_content_length(raw: object) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, bool):
        raise BackupError("invalid_content_length", 400)
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise BackupError("invalid_content_length", 400)
    if value < 0:
        raise BackupError("invalid_content_length", 400)
    return value


async def read_bounded_body(read_chunk, max_bytes: int) -> bytes:
    """Accumulate a body incrementally, never holding more than ``max_bytes``.

    Mirrors ``padiem-chat/app/bounded_request_body.py`` and the voice Worker's
    bounded reader: ask for one byte beyond the remaining budget so an
    oversized chunked body fails before it is fully buffered.
    """
    if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
        raise BackupError("request_too_large", 413)
    parts: list[bytes] = []
    total = 0
    while True:
        chunk = read_chunk(max_bytes - total + 1)
        if hasattr(chunk, "__await__"):
            chunk = await chunk
        if chunk is None or chunk == b"" or chunk == "":
            break
        if isinstance(chunk, str):
            chunk = chunk.encode("utf-8")
        elif isinstance(chunk, (bytearray, memoryview)):
            chunk = bytes(chunk)
        if not isinstance(chunk, bytes):
            raise BackupError("invalid_body", 400)
        total += len(chunk)
        if total > max_bytes:
            raise BackupError("request_too_large", 413)
        parts.append(chunk)
    return b"".join(parts)


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_manifest_path(value: object) -> str:
    """A manifest path is a relative POSIX path inside the archive."""
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise BackupError("invalid_manifest", 400)
    if "\x00" in value or "\\" in value:
        raise BackupError("invalid_manifest", 400)
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise BackupError("invalid_manifest", 400)
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise BackupError("invalid_manifest", 400)
    if any(ord(ch) < 32 for ch in value):
        raise BackupError("invalid_manifest", 400)
    return value


def validate_manifest(data: object, machine: str, backup_id: str) -> dict:
    """Validate and normalise an uploaded manifest.

    Unknown top-level fields are rejected so a caller cannot smuggle arbitrary
    credential-shaped metadata into the stored object. The returned dict keeps
    only the contract fields.
    """
    if not isinstance(data, dict):
        raise BackupError("invalid_manifest", 400)
    if set(data) != MANIFEST_KEYS:
        raise BackupError("invalid_manifest", 400)
    if data.get("kind") != MANIFEST_KIND:
        raise BackupError("invalid_manifest", 400)
    if data.get("contract_version") != CONTRACT_VERSION:
        raise BackupError("invalid_manifest", 400)
    if data.get("machine") != machine or data.get("backup_id") != backup_id:
        raise BackupError("invalid_manifest", 400)
    if data.get("payload_file") != _OBJECT_NAMES[ARTIFACT_PAYLOAD]:
        raise BackupError("invalid_manifest", 400)

    payload_bytes = data.get("payload_bytes")
    if not _is_int(payload_bytes) or not (0 <= payload_bytes <= MAX_PAYLOAD_BYTES):
        raise BackupError("invalid_manifest", 400)
    payload_sha = _manifest_digest(data.get("payload_sha256"))

    files = data.get("files")
    if not isinstance(files, list) or len(files) > MAX_MANIFEST_FILES:
        raise BackupError("invalid_manifest", 400)

    normalised_files: list[dict] = []
    seen: set[str] = set()
    total = 0
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != FILE_KEYS:
            raise BackupError("invalid_manifest", 400)
        path = validate_manifest_path(entry.get("path"))
        if path in seen:
            raise BackupError("invalid_manifest", 400)
        seen.add(path)
        size = entry.get("bytes")
        if not _is_int(size) or size < 0:
            raise BackupError("invalid_manifest", 400)
        digest = _manifest_digest(entry.get("sha256"))
        total += size
        normalised_files.append({"path": path, "bytes": size, "sha256": digest})

    if data.get("file_count") != len(normalised_files):
        raise BackupError("invalid_manifest", 400)
    if data.get("total_bytes") != total:
        raise BackupError("invalid_manifest", 400)

    created_at = data.get("created_at")
    if not isinstance(created_at, str) or not created_at or len(created_at) > 64:
        raise BackupError("invalid_manifest", 400)

    exclusions = data.get("exclusions")
    if not isinstance(exclusions, dict):
        raise BackupError("invalid_manifest", 400)
    for key, value in exclusions.items():
        if not isinstance(key, str) or not _is_int(value) or value < 0:
            raise BackupError("invalid_manifest", 400)

    # The manifest itself describes sizes; the payload cannot be smaller than
    # the uncompressed total, but it can be smaller after compression only by
    # the gzip/tar overhead, never larger than the transfer bound. The
    # authoritative size comparison happens against the stored object.
    return {
        "kind": MANIFEST_KIND,
        "contract_version": CONTRACT_VERSION,
        "machine": machine,
        "backup_id": backup_id,
        "created_at": created_at,
        "payload_file": _OBJECT_NAMES[ARTIFACT_PAYLOAD],
        "payload_bytes": payload_bytes,
        "payload_sha256": payload_sha,
        "file_count": len(normalised_files),
        "total_bytes": total,
        "files": normalised_files,
        "exclusions": {str(k): v for k, v in exclusions.items()},
    }


def parse_manifest_bytes(raw: bytes, machine: str, backup_id: str) -> dict:
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except Exception:
        raise BackupError("invalid_manifest", 400)
    return validate_manifest(decoded, machine, backup_id)


def integrity_result(manifest: dict, payload: bytes) -> dict:
    """Compare a stored payload with its manifest entry."""
    actual_sha = sha256_hex(payload)
    actual_bytes = len(payload)
    expected_sha = manifest["payload_sha256"]
    expected_bytes = manifest["payload_bytes"]
    if not hmac.compare_digest(actual_sha, expected_sha) or actual_bytes != expected_bytes:
        raise BackupError("integrity_mismatch", 409)
    return {
        "bytes": actual_bytes,
        "sha256": actual_sha,
        "file_count": manifest["file_count"],
        "total_bytes": manifest["total_bytes"],
    }
