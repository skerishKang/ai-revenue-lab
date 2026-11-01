"""Judge one OOXML archive **from its file**, without loading it whole.

#6579 step 2 needs this for a 1 GiB package that is already a file on disk. The
rules are the byte gate's own (member path, link entry, encryption, DTD and the
total-inflation ratio); only the I/O differs, so this module reuses the exact
private predicates of ``document_normalization`` instead of restating them.
``document_normalization.py`` itself stays byte-identical — its frozen SHA256
canary pins the reviewed archive authority, and this file adds no second walk
of the package rules.
"""
from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile, ZipFile, ZipInfo

from .document_normalization import (
    MAX_OOXML_TOTAL_INFLATION_RATIO,
    _ENCRYPTED_FLAG,
    _ENCRYPTED_PACKAGE_MARKER,
    _LOCAL_HEADER_SIGNATURE,
    _OLE_COMPOUND_MAGIC,
    _is_link_member,
    _read_member_bounded,
    _safe_ooxml_member,
)
from .document_semantics import DocumentNormalizationError


def _local_header_declares_encryption_in(handle, info: ZipInfo) -> bool:
    """The local flags of one entry, read by seek — the byte variant's twin."""
    offset = info.header_offset
    if offset < 0:
        return False
    try:
        handle.seek(offset)
        header = handle.read(8)
    except (OSError, ValueError):
        return False
    if len(header) < 8 or header[:4] != _LOCAL_HEADER_SIGNATURE:
        return False
    return bool(int.from_bytes(header[6:8], "little") & _ENCRYPTED_FLAG)


def _refuse_encrypted_ole_stream(handle, size: int) -> None:
    """Refuse Office's OLE wrapper without reading the whole file.

    An OOXML package that is *not* a wrapper starts with the ZIP local-header
    signature, so the marker scan only ever runs for a file that really begins
    with the OLE magic.
    """
    handle.seek(0)
    head = handle.read(len(_OLE_COMPOUND_MAGIC))
    if head != _OLE_COMPOUND_MAGIC:
        return
    handle.seek(0)
    while True:
        block = handle.read(1024 * 1024)
        if not block:
            return
        if _ENCRYPTED_PACKAGE_MARKER in block:
            raise DocumentNormalizationError(
                "ooxml_encrypted", "Password-protected OOXML package.")


def validate_ooxml_archive_path(path: object) -> None:
    """Judge one OOXML archive **from its file**, without loading it whole.

    Same rules as :func:`document_normalization.validate_ooxml_archive` — the
    path-safety predicate, the link-entry predicate, the encryption flag, the
    DTD refusal and the total-inflation ratio are the shared ones; only the I/O
    differs, so a 1 GiB package is judged from its central directory and a
    handful of local headers instead of from one `bytes` object.

    The absolute inflation judgement is the stored size on disk, exactly the
    "bytes in" the byte variant compares against. A caller that already has the
    bytes must keep using :func:`validate_ooxml_archive`; nothing about that
    function changed.
    """
    try:
        source = Path(path)
        size = source.stat().st_size
    except (OSError, TypeError, ValueError) as exc:
        raise DocumentNormalizationError(
            "ooxml_archive_size", "OOXML archive size is out of bounds."
        ) from exc
    if size <= 0:
        raise DocumentNormalizationError(
            "ooxml_archive_size", "OOXML archive size is out of bounds."
        )
    try:
        with source.open("rb") as handle:
            _refuse_encrypted_ole_stream(handle, size)

            def local_flags(info: ZipInfo) -> bool:
                return _local_header_declares_encryption_in(handle, info)

            with ZipFile(handle) as archive:
                total = 0
                for info in archive.infolist():
                    if not _safe_ooxml_member(info.filename):
                        raise DocumentNormalizationError(
                            "ooxml_unsafe_path", "OOXML archive contains an unsafe member path.")
                    if _is_link_member(info):
                        raise DocumentNormalizationError(
                            "ooxml_link_entry", "OOXML archive contains a link entry.")
                    if info.flag_bits & _ENCRYPTED_FLAG or local_flags(info):
                        raise DocumentNormalizationError(
                            "ooxml_encrypted", "Encrypted OOXML entries are not supported.")
                    total += info.file_size
                    lowered = info.filename.lower()
                    if lowered.endswith(".xml") or lowered.endswith(".rels"):
                        xml = _read_member_bounded(archive, info)
                        if b"<!doctype" in xml.lower():
                            raise DocumentNormalizationError(
                                "ooxml_dtd_rejected", "DTDs are not supported in OOXML documents.")
                if total > size * MAX_OOXML_TOTAL_INFLATION_RATIO:
                    raise DocumentNormalizationError(
                        "ooxml_total_inflation",
                        "OOXML archive inflates far beyond its stored bytes.")
    except DocumentNormalizationError:
        raise
    except (BadZipFile, OSError, ValueError, RuntimeError) as exc:
        # The byte gate's own refusal for unreadable or malformed archives; a
        # directory path fails here because its stored size is not a file size.
        raise DocumentNormalizationError("ooxml_malformed", "Malformed OOXML ZIP archive.") from exc


__all__ = ["validate_ooxml_archive_path"]
