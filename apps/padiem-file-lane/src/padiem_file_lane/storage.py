"""Stream to local disk; no fixed file-size ceiling beyond signed budget/disk."""
from __future__ import annotations

import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid

from padiem_ai_core.document_normalization import DocumentNormalizationError

FILE_PATTERN = re.compile(r"file_[a-f0-9]{32}\Z")
KINDS = {".txt": "txt", ".md": "md", ".csv": "csv", ".pdf": "pdf", ".docx": "docx", ".pptx": "pptx", ".xlsx": "xlsx"}

# Core parser refusals of an uploaded document, by constant reason code from
# padiem_ai_core.document_normalization. Chat keeps per-code guidance for
# these (#6316), so the code alone crosses the lane boundary; a parser
# exception's message can carry document content and is never passed or
# logged. Codes outside this list stay parse_failed.
PARSER_REASON_CODES = frozenset({
    # Archive gate (validate_ooxml_archive) and bounded member reads.
    "ooxml_archive_size", "ooxml_encrypted", "ooxml_unsafe_path", "ooxml_link_entry",
    "ooxml_dtd_rejected", "ooxml_entry_size", "ooxml_total_inflation", "ooxml_malformed",
    "ooxml_invalid_xml",
    # DOCX / PPTX / XLSX extraction.
    "docx_missing_part", "docx_empty", "pptx_missing_slides", "pptx_empty",
    "xlsx_invalid", "xlsx_no_sheets", "xlsx_empty",
    # PDF reader and page text.
    "pdf_magic_mismatch", "pdf_encrypted", "pdf_invalid", "pdf_no_pages",
    "pdf_empty_text", "pdf_page_text_invalid", "pdf_page_geometry_unavailable",
    # Text documents (txt/md/csv) after upload.
    "empty_document", "binary_text_rejected", "excessive_control_characters", "invalid_text",
    # Extraction dependency missing in this runtime.
    "document_dependency_unavailable",
})


class FileError(Exception):
    def __init__(self, code, status):
        self.code, self.status = code, status


def require_space(path: Path, count: int):
    if shutil.disk_usage(path).free < count:
        raise FileError("disk_full", 507)


def write_bytes(handle, data: bytes, root: Path):
    require_space(root, len(data))
    handle.write(data)


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def owner_directory(self, user_id: str) -> Path:
        # Windows folds case and trailing dots in path components. A stable
        # UTF-8 identity digest prevents two signed user IDs sharing a folder.
        return self.root / hashlib.sha256(user_id.encode("utf-8")).hexdigest()

    def new_upload(self, user_id: str, name: str):
        if not name or len(name) > 255 or any(ch in name for ch in "/\\\x00\r\n"):
            raise FileError("invalid_filename", 400)
        kind = KINDS.get(Path(name).suffix.lower())
        if not kind:
            raise FileError("unsupported_file_type", 415)
        owner = self.owner_directory(user_id)
        owner.mkdir(exist_ok=True)
        file_id = "file_" + uuid.uuid4().hex
        directory = owner / file_id
        directory.mkdir()
        return Upload(self.root, directory, file_id, name, kind)

    def directory(self, user_id: str, file_id: str) -> Path:
        if not FILE_PATTERN.fullmatch(file_id):
            raise FileError("file_not_found", 404)
        directory = self.owner_directory(user_id) / file_id
        # Metadata is published last; a partial upload is never readable.
        if not (directory / "meta.json").is_file():
            raise FileError("file_not_found", 404)
        return directory

    def meta(self, user_id, file_id):
        return json.loads((self.directory(user_id, file_id) / "meta.json").read_text(encoding="utf-8"))

    def text(self, user_id, file_id):
        directory = self.directory(user_id, file_id)
        target = directory / "text-v2.txt"
        if target.is_file():
            return target
        meta = self.meta(user_id, file_id)
        # Unique scratch files make concurrent GETs safe on Windows as well.
        pending = directory / (uuid.uuid4().hex + ".text.part")
        try:
            with pending.open("xb") as output:
                from .parsing import parse_text
                text = parse_text(directory / "data", meta["kind"])
                for offset in range(0, len(text), 64 * 1024):
                    write_bytes(output, text[offset:offset + 64 * 1024].encode("utf-8"), self.root)
                output.flush()
                os.fsync(output.fileno())
            os.replace(pending, target)
            try:
                self._write_char_count(target, len(text))
            except (OSError, FileError):
                # The window reader re-derives the count on demand; a missing
                # counter never wastes the parse that already succeeded.
                pass
        except OSError as exc:
            raise disk_error(exc) from None
        except FileError:
            raise
        except DocumentNormalizationError as exc:
            # The constant reason code carries no document content; the
            # message text never crosses this boundary.
            if exc.code in PARSER_REASON_CODES:
                raise FileError(exc.code, 422) from None
            raise FileError("parse_failed", 422) from None
        except Exception:
            # Parser exceptions can include document content. Never log/echo.
            raise FileError("parse_failed", 422) from None
        finally:
            pending.unlink(missing_ok=True)
        return target

    def char_count_path(self, path: Path) -> Path:
        return path.with_name(path.stem + ".chars")

    def _write_char_count(self, path: Path, count: int):
        pending = path.with_name(uuid.uuid4().hex + ".chars.part")
        try:
            with pending.open("xb") as output:
                write_bytes(output, str(count).encode("utf-8"), self.root)
            os.replace(pending, self.char_count_path(path))
        finally:
            pending.unlink(missing_ok=True)

    def text_char_count(self, path):
        # Total code points of the cached text, computed once at save time and
        # kept beside it. Readers never re-scan a document already counted.
        counter = self.char_count_path(path)
        if counter.is_file():
            try:
                raw = counter.read_text(encoding="utf-8").strip()
            except OSError:
                raw = ""
            if raw.isdigit():
                return int(raw)
        total = 0
        with path.open("r", encoding="utf-8", newline="") as source:
            while True:
                block = source.read(64 * 1024)
                if not block:
                    break
                total += len(block)
        try:
            self._write_char_count(path, total)
        except (OSError, FileError):
            pass
        return total


    def text_window(self, path, offset, max_chars):
        # Offsets count Unicode code points, never UTF-8 bytes. Skip in bounded
        # blocks so a distant offset does not allocate the preceding text.
        with path.open("r", encoding="utf-8", newline="") as source:
            remaining = offset
            while remaining:
                skipped = source.read(min(remaining, 64 * 1024))
                if not skipped:
                    return "", True
                remaining -= len(skipped)
            chunks = []
            remaining = max_chars
            while remaining:
                chunk = source.read(min(remaining, 64 * 1024))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            text = "".join(chunks)
            eof = not source.read(1)
        return text, eof


def disk_error(exc):
    return FileError("disk_full", 507) if exc.errno == errno.ENOSPC else FileError("storage_failed", 503)


class Upload:
    def __init__(self, root, directory, file_id, name, kind):
        self.root, self.directory = root, directory
        self.file_id, self.name, self.kind = file_id, name, kind
        self.size, self.hash = 0, hashlib.sha256()
        self.prefix = b""
        self.handle = None
        self.committed = False

    def open(self):
        self.handle = (self.directory / "data.part").open("xb")

    def write(self, block: bytes, maximum: int):
        if self.size + len(block) > maximum:
            raise FileError("ticket_size_exceeded", 413)
        write_bytes(self.handle, block, self.root)
        self.size += len(block)
        self.hash.update(block)
        if len(self.prefix) < 5:
            self.prefix = (self.prefix + block)[:5]

    def finish(self):
        if not self.size:
            raise FileError("empty_file", 422)
        if self.kind == "pdf" and self.prefix != b"%PDF-":
            raise FileError("invalid_pdf", 422)
        self.handle.flush()
        os.fsync(self.handle.fileno())
        self.handle.close()
        os.replace(self.directory / "data.part", self.directory / "data")
        meta = {"file_id": self.file_id, "name": self.name, "kind": self.kind,
                "size_bytes": self.size, "sha256": self.hash.hexdigest()}
        raw = json.dumps(meta, ensure_ascii=False).encode()
        with (self.directory / "meta.part").open("xb") as output:
            write_bytes(output, raw, self.root)
        os.replace(self.directory / "meta.part", self.directory / "meta.json")
        self.committed = True
        return meta

    def close(self):
        if self.handle is not None:
            self.handle.close()
        if not self.committed:
            shutil.rmtree(self.directory)
