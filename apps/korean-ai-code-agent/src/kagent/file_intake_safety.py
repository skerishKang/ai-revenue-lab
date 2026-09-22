"""#2824: generic bounded file intake safety gate for Claw document/file Skills.

Every Claw document/file Skill must run raw input through this gate **before**
its format parser executes. The gate is deterministic, provider-free and
network-free: it never calls a model, never uploads a file, and never needs a
credential.

Canonical flow
--------------
raw bytes -> bounded metadata -> signature inspection -> MIME classification
-> extension advisory comparison -> raw size bound -> archive safety
-> path/symlink safety -> nested archive preflight -> structural preflight
-> parser eligibility decision

Authority boundaries
--------------------
- ``FILE_EXTENSION != MIME_AUTHORITY``. The extension is advisory only. The
  content signature decides the detected format; a disagreement is reported as
  ``mismatch`` and, where a format demands structure (HWPX), is rejected.
- ``MODEL != FILE_FORMAT_IMPLEMENTATION``. No inference is used to classify.
- ``SKILL != UNBOUNDED_SHELL_SCRIPT``. This gate only decides admission; it
  never extracts to the host filesystem and never spawns a parser.

Relationship to existing modules
--------------------------------
``kagent.document_intake`` remains the *routing* layer for the review/draft
flows, and ``padiem_ai_core.document_normalization`` remains the *parser-layer*
normalizer (its OOXML archive validation runs inside extraction). Those are
parser-adjacent authorities. This module is the format-agnostic **pre-parser**
gate that decides whether a parser may be admitted at all, and it is the single
place where archive expansion, nesting, path and symlink policy for file intake
lives.

Archive inspection discipline
-----------------------------
The safety walk reads central-directory metadata only. Nesting is decided by a
**bounded content prefix** (the first few decompressed bytes), never by the
entry filename, so a ZIP payload renamed ``inner.bin`` is still recognised as a
nested archive. Entry bodies are read in full only when a nested archive is
actually recursed into, and only after that entry has already passed every
metadata size bound. Nesting is therefore not a DoS surface, and the entire
nested tree draws on one shared bounded budget rather than resetting limits per
level.
"""

from __future__ import annotations

import math

from dataclasses import dataclass, field
from enum import Enum
from io import BytesIO
from pathlib import PurePosixPath

import stat
import zipfile

__all__ = [
    "DEFAULT_POLICY",
    "MAX_SUPPORTED_ARCHIVE_DEPTH",
    "DetectedFormat",
    "FileIntakePolicy",
    "FileIntakeResult",
    "FileIntakeSafetyError",
    "IntakeDecision",
    "inspect_file",
    "sanitize_filename",
]


# --------------------------------------------------------------------------
# Signatures
# --------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF-"
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_GIF87_MAGIC = b"GIF87a"
_GIF89_MAGIC = b"GIF89a"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# RIFF....WEBP: 4-byte RIFF tag, 4-byte size, then the WEBP form tag.
_WEBP_MAGIC_PREFIX = b"RIFF"
_WEBP_MAGIC_FORM = b"WEBP"

_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")

HWPX_MEDIA_TYPE = "application/hwp+zip"

# How many decompressed bytes are read to decide whether an entry is itself an
# archive. Enough for every ZIP local/empty/spanned-header magic.
_NESTED_PREFIX_BYTES = 12

# Hard ceiling on the configurable nesting budget. A policy may lower this but
# never raise it, so a bad policy value cannot silently widen authority.
MAX_SUPPORTED_ARCHIVE_DEPTH = 4

_S_IFMT = 0o170000
_S_IFLNK = getattr(stat, "S_IFLNK", 0o120000)


class DetectedFormat(str, Enum):
    """Content-signature classification. Content always outranks extension."""

    PDF = "pdf"
    PNG = "png"
    JPEG = "jpeg"
    GIF = "gif"
    WEBP = "webp"
    ZIP_CONTAINER = "zip_container"
    HWPX_CANDIDATE = "hwpx_candidate"
    OLE_COMPOUND = "ole_compound"
    UNKNOWN = "unknown"


class IntakeDecision(str, Enum):
    """Explicit intake classification (never a bare pass/fail)."""

    SAFE_CANDIDATE = "safe_candidate"
    UNSUPPORTED = "unsupported"
    POLICY_DENIED = "policy_denied"
    ENCRYPTED = "encrypted"
    CORRUPT = "corrupt"


_DETECTED_MEDIA_TYPE = {
    DetectedFormat.PDF: "application/pdf",
    DetectedFormat.PNG: "image/png",
    DetectedFormat.JPEG: "image/jpeg",
    DetectedFormat.GIF: "image/gif",
    DetectedFormat.WEBP: "image/webp",
    DetectedFormat.ZIP_CONTAINER: "application/zip",
    DetectedFormat.HWPX_CANDIDATE: HWPX_MEDIA_TYPE,
    DetectedFormat.OLE_COMPOUND: "application/x-ole-storage",
    DetectedFormat.UNKNOWN: "application/octet-stream",
}

# Advisory only. Never used to admit a file.
_EXTENSION_MEDIA_TYPE = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".zip": "application/zip",
    ".hwpx": HWPX_MEDIA_TYPE,
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".hwp": "application/x-ole-storage",
}

# Reason codes that map onto a non-POLICY_DENIED decision.
_CORRUPT_CODES = frozenset({"archive_malformed", "archive_nested_unreadable"})
_ENCRYPTED_CODES = frozenset({"archive_encrypted"})


class FileIntakeSafetyError(RuntimeError):
    """Programming-error signal. Policy outcomes are decisions, not exceptions."""


@dataclass(frozen=True, slots=True)
class FileIntakePolicy:
    """Bounded intake policy. Defaults align with the Core document bounds.

    ``max_archive_depth`` uses the convention that the top-level archive is
    depth 0, so the default of 0 admits no nesting at all. Policy values are
    validated on construction: an unusable value raises rather than quietly
    widening or narrowing authority.
    """

    max_raw_bytes: int = 2 * 1024 * 1024
    max_archive_entries: int = 256
    max_archive_uncompressed_bytes: int = 8 * 1024 * 1024
    max_archive_depth: int = 0
    max_single_archive_entry_bytes: int = 1 * 1024 * 1024
    max_expansion_ratio: float = 200.0
    max_filename_bytes: int = 255

    def __post_init__(self) -> None:
        positive_ints = (
            "max_raw_bytes",
            "max_archive_entries",
            "max_archive_uncompressed_bytes",
            "max_single_archive_entry_bytes",
            "max_filename_bytes",
        )
        for name in positive_ints:
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise FileIntakeSafetyError(f"{name} must be a positive integer")

        if (
            not isinstance(self.max_archive_depth, int)
            or isinstance(self.max_archive_depth, bool)
            or self.max_archive_depth < 0
        ):
            raise FileIntakeSafetyError("max_archive_depth must be a non-negative integer")
        if self.max_archive_depth > MAX_SUPPORTED_ARCHIVE_DEPTH:
            raise FileIntakeSafetyError(
                f"max_archive_depth exceeds the supported maximum "
                f"({MAX_SUPPORTED_ARCHIVE_DEPTH})"
            )

        ratio = self.max_expansion_ratio
        if (
            not isinstance(ratio, (int, float))
            or isinstance(ratio, bool)
            or not math.isfinite(ratio)
            or ratio <= 0
        ):
            raise FileIntakeSafetyError("max_expansion_ratio must be a positive finite number")


DEFAULT_POLICY = FileIntakePolicy()


@dataclass(frozen=True, slots=True)
class FileIntakeResult:
    """Bounded intake decision.

    ``safe_to_parse`` is deliberately accompanied by ``detected_format`` and
    ``reason_code`` so that admission is never reduced to a single boolean that
    could be widened into blanket parser authority.
    """

    decision: IntakeDecision
    reason_code: str
    detected_format: DetectedFormat
    safe_to_parse: bool
    detected_media_type: str
    extension_media_type: str | None
    mismatch: bool
    raw_bytes: int
    filename: str
    archive_entry_count: int = 0
    archive_uncompressed_bytes: int = 0
    archive_depth_reached: int = 0
    encrypted: bool = False

    def safe_dict(self) -> dict[str, object]:
        """Bounded public projection.

        Never contains raw bytes, entry contents, host/temporary paths,
        credentials, provider payloads or exception text.
        """

        return {
            "decision": self.decision.value,
            "safe_reason_code": self.reason_code,
            "detected_media_type": self.detected_media_type,
            "extension_media_type": self.extension_media_type,
            "mismatch": self.mismatch,
            "raw_bytes": self.raw_bytes,
            "filename": self.filename,
            "archive_entry_count": self.archive_entry_count,
            "archive_uncompressed_bytes": self.archive_uncompressed_bytes,
            "archive_depth_reached": self.archive_depth_reached,
            "encrypted": self.encrypted,
            "safe_to_parse": self.safe_to_parse,
        }


@dataclass(slots=True)
class _ArchiveBudget:
    """One shared bounded budget for the whole nested archive tree.

    Limits are never reset when descending into a nested archive, so an attacker
    cannot multiply the allowance by adding levels.
    """

    policy: FileIntakePolicy
    entry_count: int = 0
    total_uncompressed: int = 0
    total_compressed: int = 0
    depth_reached: int = 0
    encrypted: bool = False
    nested_archives: int = field(default=0)


def _extension_of(filename: str) -> str:
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def sanitize_filename(filename: str, *, max_bytes: int = 255) -> str:
    """Project a caller-supplied name onto a flat, bounded, safe name."""

    if not isinstance(filename, str):
        raise FileIntakeSafetyError("filename must be a string")
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(char for char in name if char.isprintable() and char not in '/\\:*?"<>|')
    cleaned = cleaned.strip(" .")
    if not cleaned:
        return "unnamed"
    encoded = cleaned.encode("utf-8")[:max_bytes]
    return encoded.decode("utf-8", "ignore").strip() or "unnamed"


def sniff_format(payload: bytes) -> DetectedFormat:
    """Classify by content signature only. Extension is never consulted."""

    if payload.startswith(_PDF_MAGIC):
        return DetectedFormat.PDF
    if payload.startswith(_PNG_MAGIC):
        return DetectedFormat.PNG
    if payload.startswith(_JPEG_MAGIC):
        return DetectedFormat.JPEG
    if payload.startswith(_GIF87_MAGIC) or payload.startswith(_GIF89_MAGIC):
        return DetectedFormat.GIF
    if payload.startswith(_OLE_MAGIC):
        return DetectedFormat.OLE_COMPOUND
    if (
        payload.startswith(_WEBP_MAGIC_PREFIX)
        and payload[8:12] == _WEBP_MAGIC_FORM
    ):
        return DetectedFormat.WEBP
    if payload.startswith(_ZIP_MAGICS):
        return DetectedFormat.ZIP_CONTAINER
    return DetectedFormat.UNKNOWN


def _unsafe_member(name: str) -> bool:
    """Archive entry path safety. No filesystem extraction is performed."""

    if not name:
        return True
    if any(ord(char) < 32 for char in name):
        return True
    # Covers Windows separators and UNC-like \\server\share prefixes.
    if "\\" in name:
        return True
    if name.startswith("/") or "//" in name:
        return True
    if len(name) >= 2 and name[1] == ":":
        return True
    parts = PurePosixPath(name).parts
    return any(part in {"", ".", ".."} for part in parts)


def _is_link_entry(info: zipfile.ZipInfo) -> bool:
    """Symlink/link-like entry that could enable a host/workspace escape."""

    mode = (info.external_attr >> 16) & _S_IFMT
    return mode == _S_IFLNK


def _result(
    decision: IntakeDecision,
    reason_code: str,
    *,
    detected: DetectedFormat,
    extension_media: str | None,
    raw_bytes: int,
    filename: str,
    mismatch: bool = False,
    entry_count: int = 0,
    uncompressed: int = 0,
    depth_reached: int = 0,
    encrypted: bool = False,
) -> FileIntakeResult:
    return FileIntakeResult(
        decision=decision,
        reason_code=reason_code,
        detected_format=detected,
        safe_to_parse=decision is IntakeDecision.SAFE_CANDIDATE,
        detected_media_type=_DETECTED_MEDIA_TYPE[detected],
        extension_media_type=extension_media,
        mismatch=mismatch,
        raw_bytes=raw_bytes,
        filename=filename,
        archive_entry_count=entry_count,
        archive_uncompressed_bytes=uncompressed,
        archive_depth_reached=depth_reached,
        encrypted=encrypted,
    )


def _deny_from_code(code: str) -> IntakeDecision:
    if code in _ENCRYPTED_CODES:
        return IntakeDecision.ENCRYPTED
    if code in _CORRUPT_CODES:
        return IntakeDecision.CORRUPT
    return IntakeDecision.POLICY_DENIED


def _bounded_prefix(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes | None:
    """Decompress at most ``_NESTED_PREFIX_BYTES`` of an entry.

    Streaming through ``ZipFile.open`` means only as much of the deflate stream
    as needed is ever produced, so this cannot be used to expand an entry.
    """

    try:
        with archive.open(info) as handle:
            return handle.read(_NESTED_PREFIX_BYTES)
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, NotImplementedError):
        return None


def _walk_archive(payload: bytes, depth: int, budget: _ArchiveBudget) -> str | None:
    """Walk one archive level and its nested levels against one shared budget.

    Returns a denial reason code, or ``None`` when the whole subtree is within
    policy. ``depth`` 0 is the top-level archive.
    """

    policy = budget.policy
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            infos = archive.infolist()

            budget.entry_count += len(infos)
            if budget.entry_count > policy.max_archive_entries:
                return "archive_entry_count"

            for info in infos:
                if _unsafe_member(info.filename):
                    return "archive_unsafe_path"
                if _is_link_entry(info):
                    return "archive_link_entry"
                if info.flag_bits & 0x1:
                    budget.encrypted = True
                    # Fail closed immediately: never attempt to read or recurse
                    # into an encrypted entry.
                    return "archive_encrypted"
                if info.file_size > policy.max_single_archive_entry_bytes:
                    return "archive_entry_size"
                if info.compress_size <= 0 and info.file_size > 0:
                    return "archive_compressed_size_invalid"
                if info.file_size > 0:
                    compressed = max(1, info.compress_size)
                    if (info.file_size / compressed) > policy.max_expansion_ratio:
                        return "archive_expansion_ratio"
                budget.total_uncompressed += info.file_size
                budget.total_compressed += max(0, info.compress_size)
                if budget.total_uncompressed > policy.max_archive_uncompressed_bytes:
                    return "archive_total_size"

            # Aggregate ratio across the whole shared tree. The per-entry check
            # above is what stops a bomb entry being diluted by padding.
            if budget.total_compressed > 0:
                aggregate = budget.total_uncompressed / budget.total_compressed
                if aggregate > policy.max_expansion_ratio:
                    return "archive_expansion_ratio"

            budget.depth_reached = max(budget.depth_reached, depth)

            # Nesting is decided by content, not by filename.
            for info in infos:
                if info.file_size == 0:
                    continue
                prefix = _bounded_prefix(archive, info)
                if prefix is None or not prefix.startswith(_ZIP_MAGICS):
                    continue
                budget.nested_archives += 1
                if depth + 1 > policy.max_archive_depth:
                    return "archive_depth_exceeded"
                try:
                    nested_payload = archive.read(info)
                except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, NotImplementedError):
                    return "archive_nested_unreadable"
                code = _walk_archive(nested_payload, depth + 1, budget)
                if code is not None:
                    return code
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, NotImplementedError):
        return "archive_malformed"

    return None


def _inspect_archive(
    payload: bytes,
    *,
    policy: FileIntakePolicy,
    extension: str,
    extension_media: str | None,
    filename: str,
) -> FileIntakeResult:
    """Bounded archive inspection, including recursively nested archives."""

    detected = DetectedFormat.ZIP_CONTAINER
    budget = _ArchiveBudget(policy=policy)

    code = _walk_archive(payload, 0, budget)
    if code is not None:
        return _result(
            _deny_from_code(code),
            code,
            detected=detected,
            extension_media=extension_media,
            raw_bytes=len(payload),
            filename=filename,
            entry_count=budget.entry_count,
            uncompressed=budget.total_uncompressed,
            depth_reached=budget.depth_reached,
            encrypted=budget.encrypted,
            mismatch=extension == ".hwpx",
        )

    # Every size bound has passed, so the single structural read below is safe.
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            names = [info.filename for info in archive.infolist()]
            has_mimetype = "mimetype" in names
            if has_mimetype:
                declared = archive.read("mimetype").decode("utf-8", "replace").strip()
            else:
                declared = ""
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, KeyError, NotImplementedError):
        return _result(
            IntakeDecision.CORRUPT,
            "archive_malformed",
            detected=detected,
            extension_media=extension_media,
            raw_bytes=len(payload),
            filename=filename,
            entry_count=budget.entry_count,
            uncompressed=budget.total_uncompressed,
            depth_reached=budget.depth_reached,
        )

    has_section = any(name.startswith("Contents/section") for name in names)

    if has_mimetype and has_section:
        if declared == HWPX_MEDIA_TYPE:
            return _result(
                IntakeDecision.SAFE_CANDIDATE,
                "ok",
                detected=DetectedFormat.HWPX_CANDIDATE,
                extension_media=extension_media,
                raw_bytes=len(payload),
                filename=filename,
                entry_count=budget.entry_count,
                uncompressed=budget.total_uncompressed,
                depth_reached=budget.depth_reached,
                mismatch=extension != ".hwpx",
            )
        return _result(
            IntakeDecision.UNSUPPORTED,
            "hwpx_mimetype_mismatch",
            detected=detected,
            extension_media=extension_media,
            raw_bytes=len(payload),
            filename=filename,
            entry_count=budget.entry_count,
            uncompressed=budget.total_uncompressed,
            depth_reached=budget.depth_reached,
            mismatch=True,
        )

    if extension == ".hwpx":
        # A plain ZIP renamed .hwpx is not admitted as HWPX.
        return _result(
            IntakeDecision.UNSUPPORTED,
            "hwpx_structure_missing",
            detected=detected,
            extension_media=extension_media,
            raw_bytes=len(payload),
            filename=filename,
            entry_count=budget.entry_count,
            uncompressed=budget.total_uncompressed,
            depth_reached=budget.depth_reached,
            mismatch=True,
        )

    return _result(
        IntakeDecision.SAFE_CANDIDATE,
        "ok",
        detected=DetectedFormat.ZIP_CONTAINER,
        extension_media=extension_media,
        raw_bytes=len(payload),
        filename=filename,
        entry_count=budget.entry_count,
        uncompressed=budget.total_uncompressed,
        depth_reached=budget.depth_reached,
        mismatch=_mismatch(DetectedFormat.ZIP_CONTAINER, extension_media),
    )


def _mismatch(detected: DetectedFormat, extension_media: str | None) -> bool:
    if extension_media is None:
        return False
    return extension_media != _DETECTED_MEDIA_TYPE[detected]


def inspect_file(
    filename: str,
    payload: bytes,
    *,
    policy: FileIntakePolicy = DEFAULT_POLICY,
) -> FileIntakeResult:
    """Run the bounded intake gate and return an admission decision.

    Never raises for a policy outcome: oversized, encrypted, corrupt, unknown
    and denied inputs all return a decision.
    """

    if not isinstance(payload, (bytes, bytearray)):
        raise FileIntakeSafetyError("payload must be bytes")

    safe_name = sanitize_filename(filename, max_bytes=policy.max_filename_bytes)
    data = bytes(payload)
    extension = _extension_of(filename)
    extension_media = _EXTENSION_MEDIA_TYPE.get(extension)

    if not data:
        return _result(
            IntakeDecision.CORRUPT,
            "empty_payload",
            detected=DetectedFormat.UNKNOWN,
            extension_media=extension_media,
            raw_bytes=0,
            filename=safe_name,
        )

    if len(data) > policy.max_raw_bytes:
        return _result(
            IntakeDecision.POLICY_DENIED,
            "raw_too_large",
            detected=sniff_format(data),
            extension_media=extension_media,
            raw_bytes=len(data),
            filename=safe_name,
            mismatch=extension_media is not None,
        )

    detected = sniff_format(data)

    if detected is DetectedFormat.ZIP_CONTAINER:
        return _inspect_archive(
            data,
            policy=policy,
            extension=extension,
            extension_media=extension_media,
            filename=safe_name,
        )

    if detected is DetectedFormat.OLE_COMPOUND:
        return _result(
            IntakeDecision.UNSUPPORTED,
            "legacy_ole_compound_unsupported",
            detected=detected,
            extension_media=extension_media,
            raw_bytes=len(data),
            filename=safe_name,
            mismatch=_mismatch(detected, extension_media),
        )

    if detected is DetectedFormat.UNKNOWN:
        return _result(
            IntakeDecision.UNSUPPORTED,
            "unknown_format",
            detected=detected,
            extension_media=extension_media,
            raw_bytes=len(data),
            filename=safe_name,
            mismatch=extension_media is not None,
        )

    return _result(
        IntakeDecision.SAFE_CANDIDATE,
        "ok",
        detected=detected,
        extension_media=extension_media,
        raw_bytes=len(data),
        filename=safe_name,
        mismatch=_mismatch(detected, extension_media),
    )