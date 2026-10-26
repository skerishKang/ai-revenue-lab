"""Stream to local disk; no fixed file-size ceiling beyond signed budget/disk."""
from __future__ import annotations

import codecs
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import uuid

FILE_PATTERN = re.compile(r"file_[a-f0-9]{32}\Z")
KINDS = {".txt": "txt", ".md": "md", ".csv": "csv", ".pdf": "pdf"}


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
        target = directory / "text.txt"
        if target.is_file():
            return target
        meta = self.meta(user_id, file_id)
        # Unique scratch files make concurrent GETs safe on Windows as well.
        pending = directory / (uuid.uuid4().hex + ".text.part")
        try:
            with pending.open("xb") as output:
                if meta["kind"] == "pdf":
                    from pypdf import PdfReader
                    with (directory / "data").open("rb") as source:
                        reader = PdfReader(source)
                        if reader.is_encrypted:
                            raise FileError("encrypted_pdf", 422)
                        for index, page in enumerate(reader.pages):
                            text = page.extract_text() or ""
                            if index:
                                write_bytes(output, b"\n", self.root)
                            write_bytes(output, text.encode("utf-8"), self.root)
                else:
                    decoder = codecs.getincrementaldecoder("utf-8-sig")()
                    with (directory / "data").open("rb") as source:
                        while block := source.read(64 * 1024):
                            write_bytes(output, decoder.decode(block).encode("utf-8"), self.root)
                        write_bytes(output, decoder.decode(b"", final=True).encode("utf-8"), self.root)
                output.flush()
                os.fsync(output.fileno())
            os.replace(pending, target)
        except OSError as exc:
            raise disk_error(exc) from None
        except FileError:
            raise
        except Exception:
            # Parser exceptions can include document content. Never log/echo.
            raise FileError("parse_failed", 422) from None
        finally:
            pending.unlink(missing_ok=True)
        return target


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
