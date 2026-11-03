"""Persistent remote jobs for the existing PC execution authority.

Background receipts follow Hermes Agent process management (MIT, Nous Research).
The injected runner retains all transport, command validation and cancellation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time


class RemoteBackgroundJobs:
    """Durable jobs over an already-authorized remote command runner.

    The runner is the existing MeshCentral executor, never a local subprocess.
    Only a trusted claimed dispatch enters start(). Owner scope is supplied by
    that dispatcher and checked on every public receipt/output operation.
    """

    def __init__(self, directory, *, runner):
        if not callable(runner):
            raise TypeError("an authorized remote runner is required")
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.lock = threading.RLock()
        self.active = {}
        for path in self.root.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("state") == "running":
                    # Execution may have happened; a restart never replays it.
                    record.update(state="failed", termination="no_reply", exit_code=None,
                                  finished_at=time.time())
                    self._save(record)
            except (OSError, ValueError, TypeError, KeyError):
                continue

    @staticmethod
    def _identity(job_id, owner):
        import hashlib
        if not isinstance(job_id, str) or not job_id or not isinstance(owner, str) or not owner:
            raise ValueError("job and owner are required")
        return hashlib.sha256(json.dumps([owner, job_id], separators=(",", ":")).encode()).hexdigest()

    def _path(self, job_id, owner, suffix):
        return self.root / (self._identity(job_id, owner) + suffix)

    def _load(self, job_id, owner):
        try:
            record = json.loads(self._path(job_id, owner, ".json").read_text(encoding="utf-8"))
            if record["job_id"] != job_id or record["owner"] != owner:
                raise KeyError("unknown job")
            return record
        except (OSError, ValueError, TypeError, KeyError):
            raise KeyError("unknown job") from None

    @staticmethod
    def _atomic(path, body):
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def _save(self, record):
        self._atomic(self._path(record["job_id"], record["owner"], ".json"),
                     json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))

    def start(self, dispatch, *, owner):
        from copy import deepcopy
        if not isinstance(dispatch, dict):
            raise TypeError("a trusted claimed dispatch is required")
        dispatch = deepcopy(dispatch)
        job_id = dispatch.get("dispatch_id")
        key = self._identity(job_id, owner)
        with self.lock:
            try:
                record = self._load(job_id, owner)
            except KeyError:
                record = None
            if record is not None:
                # A re-claimed completed/interrupted dispatch is delivery only.
                # Its freshly issued nonce may change; execution facts may not.
                previous = dict(record["dispatch"])
                current = dict(dispatch)
                previous.pop("nonce", None)
                current.pop("nonce", None)
                if previous != current:
                    raise ValueError("job dispatch does not match its receipt")
                record["dispatch"] = dispatch
                record["delivered"] = False
                self._save(record)
                return {"job_id": job_id, "state": record["state"]}
            record = {"job_id": job_id, "owner": owner, "dispatch": dispatch,
                      "state": "running", "started_at": time.time(), "finished_at": None,
                      "termination": None, "exit_code": None, "delivered": False,
                      "output_size": 0, "cancel_requested": False}
            self._atomic(self._path(job_id, owner, ".log"), b"")
            self._save(record)
            cancel = threading.Event()
            self.active[key] = cancel
            worker = threading.Thread(target=self._watch_remote,
                                      args=(dispatch, owner, cancel), daemon=True)
            try:
                worker.start()
            except BaseException:
                self.active.pop(key, None)
                record.update(state="failed", termination="not_executed",
                              finished_at=time.time())
                self._save(record)
                raise
            return {"job_id": job_id, "state": "running"}

    def _watch_remote(self, dispatch, owner, cancel):
        job_id = dispatch["dispatch_id"]
        try:
            result = self.runner(dispatch, cancel_probe=cancel.is_set)
            if not isinstance(result, dict):
                raise TypeError("remote runner result must be a mapping")
            body = result.get("body", b"")
            if not isinstance(body, bytes):
                raise TypeError("remote runner output must be bytes")
            termination = result.get("termination")
            exit_code = result.get("exit_code")
            if termination not in {"exited", "cancelled", "timed_out", "no_reply",
                                   "no_exit_code", "not_executed", "output_too_large", "bad_reply"}:
                raise ValueError("remote runner termination is invalid")
            if exit_code is not None and type(exit_code) is not int:
                raise ValueError("remote runner exit code is invalid")
        except Exception:
            body, termination, exit_code = b"", "no_reply", None
        with self.lock:
            record = self._load(job_id, owner)
            self._atomic(self._path(job_id, owner, ".log"), body)
            record.update(
                state="killed" if termination == "cancelled" else
                      ("done" if termination == "exited" and exit_code == 0 else "failed"),
                termination=termination, exit_code=exit_code, output_size=len(body),
                finished_at=time.time(),
            )
            self._save(record)
            self.active.pop(self._identity(job_id, owner), None)

    def status(self, job_id, *, owner):
        with self.lock:
            record = self._load(job_id, owner)
            return {key: record[key] for key in
                    ("job_id", "state", "started_at", "finished_at", "exit_code",
                     "output_size", "cancel_requested")}

    def output(self, job_id, offset, length, *, owner):
        if type(offset) is not int or type(length) is not int or offset < 0 or length < 0:
            raise ValueError("offset and length must be non-negative integers")
        with self.lock:
            self._load(job_id, owner)
            with self._path(job_id, owner, ".log").open("rb") as source:
                source.seek(offset)
                return source.read(length).decode("utf-8", errors="replace")

    def kill(self, job_id, *, owner):
        with self.lock:
            record = self._load(job_id, owner)
            cancel = self.active.get(self._identity(job_id, owner))
            if record["state"] != "running" or cancel is None:
                return False
            record["cancel_requested"] = True
            self._save(record)
            cancel.set()
            return True

    def list(self, owner):
        with self.lock:
            results = []
            for path in self.root.glob("*.json"):
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("owner") == owner:
                    results.append(self.status(record["job_id"], owner=owner))
            return sorted(results, key=lambda row: row["started_at"])

    def pending_results(self):
        """Internal dispatcher delivery queue; no caller-supplied identities."""
        with self.lock:
            results = []
            for path in self.root.glob("*.json"):
                record = json.loads(path.read_text(encoding="utf-8"))
                if record["state"] != "running" and not record["delivered"]:
                    body = self._path(record["job_id"], record["owner"], ".log").read_bytes()
                    results.append((record, body))
            return sorted(results, key=lambda pair: pair[0]["started_at"])

    def acknowledge(self, job_id, *, owner):
        with self.lock:
            record = self._load(job_id, owner)
            record["delivered"] = True
            self._save(record)
