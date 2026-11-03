"""Durable PC output RPCs served by the existing authenticated COM2 queue door.

Upload parts stay below that door's existing request limit. Neither the model
nor a handle supplies authority: every operation is scoped to the verified
Chat user, subject, run and selected device.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import time

from padiem_ai_core.output_store import (
    OutputStore, configured_retention_seconds, exclusive_file_lock,
)

PC_OUTPUT_METHODS = frozenset({
    "begin_pc_output", "append_pc_output", "finish_pc_output",
    "read_pc_output", "search_pc_output",
})
_CHUNK_BYTES = 65536
_ID = re.compile(r"[0-9a-f]{64}\Z")


class PcOutputStore:
    def __init__(self, directory, *, history_store=None):
        self.directory = Path(directory)
        self.store = OutputStore(
            self.directory / "outputs", retention_seconds=configured_retention_seconds())
        self.history = history_store
        self.index_directory = self.directory / "account-index"
        self.deleted_directory = self.directory / "deleted-accounts"
        self.lock_directory = self.directory / ".account-locks"
        self._last_cleanup = 0.0

    @staticmethod
    def _account_hash(user_id):
        if not isinstance(user_id, str) or not user_id or len(user_id) > 1024:
            raise ValueError("output account required")
        return hashlib.sha256(user_id.encode("utf-8")).hexdigest()

    @staticmethod
    def _owner(user_id, subject_id, run_id, device_id):
        values = [user_id, subject_id, run_id, device_id]
        if any(not isinstance(v, str) or not v or len(v) > 1024 for v in values):
            raise ValueError("output owner required")
        return json.dumps(values, ensure_ascii=True, separators=(",", ":"))

    def _account_guard(self, user_id):
        return exclusive_file_lock(self.lock_directory / (self._account_hash(user_id) + ".lock"))

    def _assert_account_active(self, user_id):
        account_hash = self._account_hash(user_id)
        if (self.deleted_directory / (account_hash + ".marker")).exists():
            raise ValueError("account output data has been deleted")
        return account_hash

    def _index_owner(self, user_id, owner):
        account_hash = self._assert_account_active(user_id)
        scope_hash = hashlib.sha256(owner.encode("utf-8")).hexdigest()
        account_index = self.index_directory / account_hash
        account_index.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker = account_index / (scope_hash + ".scope")
        if not marker.exists():
            marker.touch(mode=0o600, exist_ok=False)
        return scope_hash

    def _directory(self, owner, *, user_id):
        scope_hash = self._index_owner(user_id, owner)
        root = self.directory / "uploads"
        now = time.time()
        if now - self._last_cleanup >= 60:
            # Include abandoned runs: they may never issue another owner-scoped read.
            self._last_cleanup = now
            cutoff = now - self.store.retention_seconds
            for pattern in ("*/*.part", "*/*.done", "*/*.ref", "*/*.tmp"):
                for path in root.glob(pattern):
                    try:
                        if path.stat().st_mtime <= cutoff:
                            path.unlink(missing_ok=True)
                            if path.suffix == ".part":
                                path.with_suffix(".json").unlink(missing_ok=True)
                    except FileNotFoundError:
                        pass
        directory = root / scope_hash
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        return directory

    def _upload(self, owner, upload_id, *, user_id):
        if not isinstance(upload_id, str) or not _ID.fullmatch(upload_id):
            raise ValueError("invalid upload reference")
        directory = self._directory(owner, user_id=user_id)
        meta = json.loads((directory / (upload_id + ".json")).read_text(encoding="utf-8"))
        return directory / (upload_id + ".part"), meta

    async def begin_pc_output(self, *, user_id, subject_id, run_id, device_id,
                              source, size, sha256, dispatch_id=""):
        owner = self._owner(user_id, subject_id, run_id, device_id)
        if (not isinstance(source, str) or not source or len(source) > 1024
                or type(size) is not int or size < 0
                or not isinstance(sha256, str) or not _ID.fullmatch(sha256)):
            raise ValueError("invalid output metadata")
        if dispatch_id:
            if self.history is None:
                raise ValueError("dispatch authority unavailable")
            row = await self.history.get_pc_output_dispatch_for_owner(
                user_id=user_id, dispatch_id=dispatch_id)
            if (not row or row.get("run_id") != run_id or row.get("state") not in {"done", "failed"}
                    or row.get("device_id") != device_id
                    or row.get("result_sha256") != sha256):
                raise ValueError("output dispatch unavailable")
        with self._account_guard(user_id):
            directory = self._directory(owner, user_id=user_id)
            cache_key = hashlib.sha256(
                json.dumps([source, dispatch_id, sha256], separators=(",", ":")).encode()
            ).hexdigest()
            index = directory / (cache_key + ".ref")
            if index.exists():
                ref = json.loads(index.read_text(encoding="utf-8"))
                try:
                    self.store.read(ref["handle"], owner=owner, offset=0, length=0)
                    return {"output_ref": ref}
                except FileNotFoundError:
                    index.unlink(missing_ok=True)
            upload_id = secrets.token_hex(32)
            meta = {"source": source, "size": size, "sha256": sha256, "cache_key": cache_key}
            (directory / (upload_id + ".part")).touch(mode=0o600, exist_ok=False)
            (directory / (upload_id + ".json")).write_text(json.dumps(meta), encoding="utf-8")
            return {"upload_id": upload_id, "offset": 0}

    async def append_pc_output(self, *, user_id, subject_id, run_id, device_id,
                               upload_id, offset, data):
        owner = self._owner(user_id, subject_id, run_id, device_id)
        if type(offset) is not int or offset < 0 or not isinstance(data, str):
            raise ValueError("invalid upload part")
        raw = base64.b64decode(data, validate=True)
        if len(raw) > _CHUNK_BYTES:
            raise ValueError("upload part exceeds transport budget")
        with self._account_guard(user_id):
            path, meta = self._upload(owner, upload_id, user_id=user_id)
            with path.open("r+b") as stream:
                stream.seek(0, os.SEEK_END)
                current = stream.tell()
                if current != offset:
                    # Retrying an acknowledged-lost part is idempotent, never appended twice.
                    if current < offset + len(raw):
                        raise ValueError("upload offset mismatch")
                    stream.seek(offset)
                    if stream.read(len(raw)) != raw:
                        raise ValueError("upload part mismatch")
                    return {"offset": offset + len(raw)}
                if current + len(raw) > meta["size"]:
                    raise ValueError("upload size mismatch")
                stream.write(raw)
            return {"offset": offset + len(raw)}

    async def finish_pc_output(self, *, user_id, subject_id, run_id, device_id, upload_id):
        owner = self._owner(user_id, subject_id, run_id, device_id)
        if not isinstance(upload_id, str) or not _ID.fullmatch(upload_id):
            raise ValueError("invalid upload reference")
        with self._account_guard(user_id):
            receipt = self._directory(owner, user_id=user_id) / (upload_id + ".done")
            if receipt.exists():
                ref = json.loads(receipt.read_text(encoding="utf-8"))
                self.store.read(ref["handle"], owner=owner, offset=0, length=0)
                return ref
            path, meta = self._upload(owner, upload_id, user_id=user_id)
            raw = path.read_bytes()
            if len(raw) != meta["size"] or hashlib.sha256(raw).hexdigest() != meta["sha256"]:
                raise ValueError("upload integrity mismatch")
            ref = self.store.store(raw, owner=owner, source=meta["source"])
            index = path.parent / (meta["cache_key"] + ".ref")
            staged = path.parent / (upload_id + ".ref.tmp")
            staged.write_text(json.dumps(ref), encoding="utf-8")
            os.replace(staged, index)
            receipt_staged = receipt.with_suffix(".done.tmp")
            receipt_staged.write_text(json.dumps(ref), encoding="utf-8")
            os.replace(receipt_staged, receipt)
            path.unlink(missing_ok=True)
            path.with_suffix(".json").unlink(missing_ok=True)
            return ref

    async def read_pc_output(self, *, user_id, subject_id, run_id, device_id,
                             handle, offset, length):
        owner = self._owner(user_id, subject_id, run_id, device_id)
        if type(length) is not int or not 0 <= length <= _CHUNK_BYTES:
            raise ValueError("read exceeds context transport budget")
        with self._account_guard(user_id):
            self._assert_account_active(user_id)
            content = self.store.read(handle, owner=owner, offset=offset, length=length)
            return {"handle": handle, "offset": offset, "length": length, "content": content}

    async def search_pc_output(self, *, user_id, subject_id, run_id, device_id,
                               handle, query):
        owner = self._owner(user_id, subject_id, run_id, device_id)
        with self._account_guard(user_id):
            self._assert_account_active(user_id)
            hits = self.store.search(handle, owner=owner, pattern=query, max_hits=20)
            # Offsets still refer to the full immutable output; read_output recovers any range.
            for hit in hits:
                hit["line"] = hit["line"][:4096]
            return {"handle": handle, "hits": hits}

    def delete_account(self, user_id):
        """Tombstone one owner and remove every indexed upload/output scope."""
        account_hash = self._account_hash(user_id)
        with self._account_guard(user_id):
            self.deleted_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            tombstone = self.deleted_directory / (account_hash + ".marker")
            if not tombstone.exists():
                tombstone.touch(mode=0o600, exist_ok=False)

            account_index = self.index_directory / account_hash
            scopes = []
            if account_index.exists():
                for marker in account_index.glob("*.scope"):
                    scope_hash = marker.stem
                    if not _ID.fullmatch(scope_hash):
                        raise RuntimeError("output owner index is invalid")
                    scopes.append(scope_hash)
                for scope_hash in scopes:
                    uploads = self.directory / "uploads" / scope_hash
                    if uploads.is_symlink():
                        uploads.unlink()
                    elif uploads.exists():
                        shutil.rmtree(uploads)
                    self.store.delete_owner_hash(scope_hash)
                shutil.rmtree(account_index)
            return len(scopes)
