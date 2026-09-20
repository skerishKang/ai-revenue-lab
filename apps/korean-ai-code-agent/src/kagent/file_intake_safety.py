"""#2824: generic bounded file intake safety gate for Claw document/file Skills.

Every Claw document/file Skill must run raw input through this gate **before**
its format parser executes. The gate is deterministic, provider-free and
network-free: it never calls a model, never uploads a file, and never needs a
credential.

Canonical flow
--------------
raw bytes -> bounded metadata -> signature inspection -> MIME classification
-> extension advisory comparison -> raw size bound -> archive safety
-> path/symlink safety -> structural preflight -> parser eligibility decision

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
place where archive expansion, path and symlink policy for file intake lives.

Archive inspection reads central-directory metadata only. Entry contents are
never decompressed during the safety loop, so inspection itself is not a DoS
surface. The single optional read (the HWPX ``mimetype`` entry) happens only
after every size bound has already passed.
"""

from __future__ import annotations

import stat
import zipfile

from dataclasses import dataclass
from enum import Enum
from io import BytesIO
from pathlib import PurePosixPath

__all__ = [
    "DEFAULT_POLICY",
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

# Recognised container suffixes. Presence of one of these inside an archive is
# what the nested-archive depth policy acts on.
_NESTED_ARCHIVE_SUFFIXES = (
    ".zip",
    ".hwpx",
    ".docx",
    ".xlsx",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".jar",
    ".apk",
)

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


class FileIntakeSafetyError(RuntimeError):
    """Programming-error signal. Policy outcomes are decisions, not exceptions."""


@dataclass(frozen=True, slots=True)
class FileIntakePolicy:
    """Bounded intake policy. Defaults align with the Core document bounds."""

    max_raw_bytes: int = 2 * 1024 * 1024
    max_archive_entries: int = 256
    max_archive_uncompressed_bytes: int = 8 * 1024 * 1024
    max_archive_depth: int = 1
    max_single_archive_entry_bytes: int = 1 * 1024 * 1024
    max_expansion_ratio: float = 200.0
    max_filename_bytes: int = 255


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
            "encrypted": self.encrypted,
            "safe_to_parse": self.safe_to_parse,
        }


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


def _looks_nested(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith(_NESTED_ARCHIVE_SUFFIXES)


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
        encrypted=encrypted,
    )


def _inspect_archive(
    payload: bytes,
    *,
    policy: FileIntakePolicy,
    extension: str,
    extension_media: str | None,
    filename: str,
) -> FileIntakeResult:
    """Bounded archive inspection. Reads central-directory metadata only."""

    detected = DetectedFormat.ZIP_CONTAINER
    try:
        with zipfile.ZipFile(BytesIO(payload)) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError):
        return _result(
            IntakeDecision.CORRUPT,
            "archive_malformed",
            detected=detected,
            extension_media=extension_media,
            raw_bytes=len(payload),
            filename=filename,
            mismatch=extension in {".hwpx"},
        )

    if len(infos) > policy.max_archive_entries:
        return _result(
            IntakeDecision.POLICY_DENIED,
            "archive_entry_count",
            detected=detected,
            extension_media=extension_media,
            raw_bytes=len(payload),
            filename=filename,
            entry_count=len(infos),
            mismatch=extension == ".hwpx",
        )

    total = 0
    encrypted = False
    for info in infos:
        if _unsafe_member(info.filename):
            return _result(
                IntakeDecision.POLICY_DENIED,
                "archive_unsafe_path",
                detected=detected,
                extension_media=extension_media,
                raw_bytes=len(payload),
                filename=filename,
                entry_count=len(infos),
                mismatch=extension == ".hwpx",
            )
        if _is_link_entry(info):
            return _result(
                IntakeDecision.POLICY_DENIED,
                "archive_link_entry",
                detected=detected,
                extension_media=extension_media,
                raw_bytes=len(payload),
                filename=filename,
                entry_count=len(infos),
                mismatch=extension == ".hwpx",
            )
        if info.flag_bits & 0x1:
            encrypted = True
        if info.file_size > policy.max_single_archive_entry_bytes:
            return _result(
                IntakeDecision.POLICY_DENIED,
                "archive_entry_size",
                detected=detected,
                extension_media=extension_media,
                raw_bytes=len(payload),
                filename=filename,
                entry_count=len(infos),
                encrypted=encrypted,
                mismatch=extension == ".hwpx",
            )
        total += info.file_size
        if total > policy.max_archive_uncompressed_bytes:
            return _result(
                IntakeDecision.POLICY_DENIED,
                "archive_total_size",
                detected=detected,
                extension_media=extension_media,
                raw_bytes=len(payload),
                filename=filename,
                entry_count=len(infos),
                uncompressed=total,
                encrypted=encrypted,
                mismatch=extension == ".hwpx",
            )
        if policy.max_archive_depth < 2 and _looks_nested(info.filename):
            return _result(
                IntakeDecision.POLICY_DENIED,
                "nested_archive_not_allowed",
                detected=detected,
                extension_media=extension_media,
                raw_bytes=len(payload),
                filename=filename,
                entry_count=len(infos),
                uncompressed=total,
                encrypted=encrypted,
                mismatch=extension == ".hwpx",
            )

    if encrypted:
        return _result(
            IntakeDecision.ENCRYPTED,
            "archive_encrypted",
            detected=detected,
            extension_media=extension_media,
            raw_bytes=len(payload),
            filename=filename,
            entry_count=len(infos),
            uncompressed=total,
            encrypted=True,
            mismatch=extension == ".hwpx",
        )

    compressed = max(1, len(payload))
    if (total / compressed) > policy.max_expansion_ratio:
        return _result(
            IntakeDecision.POLICY_DENIED,
            "archive_expansion_ratio",
            detected=detected,
            extension_media=extension_media,
            raw_bytes=len(payload),
            filename=filename,
            entry_count=len(infos),
            uncompressed=total,
            mismatch=extension == ".hwpx",
        )

    names = [info.filename for info in infos]
    has_mimetype = "mimetype" in names
    has_section = any(name.startswith("Contents/section") for name in names)

    # Bounded structural preflight: only reached once every size bound passed.
    if has_mimetype and has_section:
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                declared = archive.read("mimetype").decode("utf-8", "replace").strip()
        except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, KeyError):
            declared = ""
        if declared == HWPX_MEDIA_TYPE:
            return _result(
                IntakeDecision.SAFE_CANDIDATE,
                "ok",
                detected=DetectedFormat.HWPX_CANDIDATE,
                extension_media=extension_media,
                raw_bytes=len(payload),
                filename=filename,
                entry_count=len(infos),
                uncompressed=total,
                mismatch=extension != ".hwpx",
            )
        return _result(
            IntakeDecision.UNSUPPORTED,
            "hwpx_mimetype_mismatch",
            detected=detected,
            extension_media=extension_media,
            raw_bytes=len(payload),
            filename=filename,
            entry_count=len(infos),
            uncompressed=total,
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
            entry_count=len(infos),
            uncompressed=total,
            mismatch=True,
        )

    return _result(
        IntakeDecision.SAFE_CANDIDATE,
        "ok",
        detected=DetectedFormat.ZIP_CONTAINER,
        extension_media=extension_media,
        raw_bytes=len(payload),
        filename=filename,
        entry_count=len(infos),
        uncompressed=total,
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
