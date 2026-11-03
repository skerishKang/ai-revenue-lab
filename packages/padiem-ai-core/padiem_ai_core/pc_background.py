"""Persistent remote jobs for the existing PC execution authority.

Background receipts follow Hermes Agent process management (MIT, Nous Research).
The injected runner retains all transport, command validation and cancellation.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import threading
import time

from .output_store import configured_retention_seconds, exclusive_file_lock

_LOG = logging.getLogger(__name__)
_CLEANUP_INTERVAL_SECONDS = 60.0


def _retention_seconds(value):
    if value is None:
        value = configured_retention_seconds()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("retention must be a positive number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("retention must be a positive number")
    return float(value)


def _remove_if_present(path):
    try:
        path.unlink()
        return 1
    except FileNotFoundError:
        return 0


def _owner_user_id(owner):
    if not isinstance(owner, str):
        return None
    try:
        identity = json.loads(owner)
    except (TypeError, ValueError):
        return None
    if isinstance(identity, list) and identity and isinstance(identity[0], str) and identity[0]:
        return identity[0]
    return None


def _cleanup_expired_locked(root, *, now, retention_seconds):
    cutoff = now - retention_seconds
    if not root.exists():
        return 0
    removed_files = 0
    for receipt in root.glob("*.json"):
        try:
            record = json.loads(receipt.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(record, dict) or record.get("state") == "running":
            continue
        finished = record.get("finished_at")
        if (isinstance(finished, bool) or not isinstance(finished, (int, float))
                or not math.isfinite(finished) or finished > cutoff):
            continue
        log = receipt.with_suffix(".log")
        removed_files += _remove_if_present(log)
        removed_files += _remove_if_present(receipt)
        for temporary in (receipt.with_suffix(".json.tmp"), log.with_suffix(".log.tmp")):
            removed_files += _remove_if_present(temporary)

    # Remove aged output left without a readable receipt after an interrupted write.
    for log in root.glob("*.log"):
        if not log.with_suffix(".json").exists() and log.stat().st_mtime <= cutoff:
            removed_files += _remove_if_present(log)
    for temporary in root.glob("*.tmp"):
        if temporary.stat().st_mtime <= cutoff:
            removed_files += _remove_if_present(temporary)
    return removed_files


def cleanup_expired_background_jobs(directory, *, now=None, retention_seconds=None):
    """Delete terminal receipts and logs at the shared output-store retention boundary."""
    root = Path(directory)
    retention = _retention_seconds(retention_seconds)
    moment = time.time() if now is None else now
    if isinstance(moment, bool) or not isinstance(moment, (int, float)) or not math.isfinite(moment):
        raise ValueError("cleanup time must be finite")
    if not root.exists():
        return 0
    with exclusive_file_lock(root / ".jobs.lock"):
        removed = _cleanup_expired_locked(root, now=moment, retention_seconds=retention)
    _LOG.info("claw background cleanup files_removed=%d", removed)
    return removed


def delete_account_background_jobs(directory, user_id):
    """Remove one user's durable receipts and logs; unreadable ownership fails closed."""
    if not isinstance(user_id, str) or not user_id or len(user_id) > 1024:
        raise ValueError("a valid account owner is required")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    deleted = 0
    with exclusive_file_lock(root / ".jobs.lock"):
        receipts = []
        for receipt in root.glob("*.json"):
            try:
                record = json.loads(receipt.read_text(encoding="utf-8"))
                owner = record["owner"]
            except (OSError, KeyError, TypeError, ValueError, UnicodeDecodeError):
                raise RuntimeError("background job ownership is unreadable") from None
            if _owner_user_id(owner) is None:
                raise RuntimeError("background job ownership is unreadable")
            if _owner_user_id(owner) == user_id:
                receipts.append(receipt)
        deleted_accounts = root / "deleted-accounts"
        deleted_accounts.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker = deleted_accounts / (hashlib.sha256(user_id.encode("utf-8")).hexdigest() + ".marker")
        if not marker.exists():
            marker.touch(mode=0o600, exist_ok=False)
        for receipt in receipts:
            log = receipt.with_suffix(".log")
            for artifact in (
                log,
                receipt,
                receipt.with_suffix(".json.tmp"),
                log.with_suffix(".log.tmp"),
            ):
                _remove_if_present(artifact)
            deleted += 1
    return deleted


class RemoteBackgroundJobs:
    """Durable jobs over an already-authorized remote command runner.

    The runner is the existing MeshCentral executor, never a local subprocess.
    Only a trusted claimed dispatch enters start(). Owner scope is supplied by
    that dispatcher and checked on every public receipt/output operation.
    """

    def __init__(self, directory, *, runner, retention_seconds=None, clock=time.time):
        if not callable(runner):
            raise TypeError("an authorized remote runner is required")
        self.root = Path(directory)
        self.root.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.lock = threading.RLock()
        self.active = {}
        self.retention_seconds = _retention_seconds(retention_seconds)
        self.clock = clock
        self._last_cleanup = 0.0
        with self._guard():
            for path in self.root.glob("*.json"):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    if record.get("state") == "running":
                        # Execution may have happened; a restart never replays it.
                        record.update(state="failed", termination="no_reply", exit_code=None,
                                      finished_at=self.clock())
                        self._save(record)
                except (OSError, ValueError, TypeError, KeyError):
                    continue

    @contextmanager
    def _guard(self):
        with self.lock:
            with exclusive_file_lock(self.root / ".jobs.lock"):
                yield

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

    def cleanup_expired(self, *, now=None):
        moment = self.clock() if now is None else now
        with self._guard():
            removed = _cleanup_expired_locked(
                self.root, now=moment, retention_seconds=self.retention_seconds)
            self._last_cleanup = time.monotonic()
        _LOG.info("claw background cleanup files_removed=%d", removed)
        return removed

    def start(self, dispatch, *, owner):
        from copy import deepcopy
        if not isinstance(dispatch, dict):
            raise TypeError("a trusted claimed dispatch is required")
        dispatch = deepcopy(dispatch)
        job_id = dispatch.get("dispatch_id")
        key = self._identity(job_id, owner)
        with self._guard():
            account_id = _owner_user_id(owner)
            if account_id is not None:
                marker = self.root / "deleted-accounts" / (
                    hashlib.sha256(account_id.encode("utf-8")).hexdigest() + ".marker")
                if marker.exists():
                    raise ValueError("account background jobs were deleted")
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
                      "state": "running", "started_at": self.clock(), "finished_at": None,
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
                              finished_at=self.clock())
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
        with self._guard():
            try:
                record = self._load(job_id, owner)
            except KeyError:
                # Account deletion removed the receipt while the remote call was in flight.
                self.active.pop(self._identity(job_id, owner), None)
                return
            self._atomic(self._path(job_id, owner, ".log"), body)
            record.update(
                state="killed" if termination == "cancelled" else
                      ("done" if termination == "exited" and exit_code == 0 else "failed"),
                termination=termination, exit_code=exit_code, output_size=len(body),
                finished_at=self.clock(),
            )
            self._save(record)
            self.active.pop(self._identity(job_id, owner), None)

    def status(self, job_id, *, owner):
        with self._guard():
            record = self._load(job_id, owner)
            return {key: record[key] for key in
                    ("job_id", "state", "started_at", "finished_at", "exit_code",
                     "output_size", "cancel_requested")}

    def output(self, job_id, offset, length, *, owner):
        if type(offset) is not int or type(length) is not int or offset < 0 or length < 0:
            raise ValueError("offset and length must be non-negative integers")
        with self._guard():
            self._load(job_id, owner)
            with self._path(job_id, owner, ".log").open("rb") as source:
                source.seek(offset)
                return source.read(length).decode("utf-8", errors="replace")

    def kill(self, job_id, *, owner):
        with self._guard():
            record = self._load(job_id, owner)
            cancel = self.active.get(self._identity(job_id, owner))
            if record["state"] != "running" or cancel is None:
                return False
            record["cancel_requested"] = True
            self._save(record)
            cancel.set()
            return True

    def list(self, owner):
        with self._guard():
            results = []
            for path in self.root.glob("*.json"):
                record = json.loads(path.read_text(encoding="utf-8"))
                if record.get("owner") == owner:
                    results.append({key: record[key] for key in
                                    ("job_id", "state", "started_at", "finished_at",
                                     "exit_code", "output_size", "cancel_requested")})
            return sorted(results, key=lambda row: row["started_at"])

    def pending_results(self):
        """Internal dispatcher delivery queue; no caller-supplied identities."""
        with self._guard():
            now = time.monotonic()
            if now - self._last_cleanup >= _CLEANUP_INTERVAL_SECONDS:
                removed = _cleanup_expired_locked(
                    self.root, now=self.clock(), retention_seconds=self.retention_seconds)
                self._last_cleanup = now
                _LOG.info("claw background cleanup files_removed=%d", removed)
            results = []
            for path in self.root.glob("*.json"):
                record = json.loads(path.read_text(encoding="utf-8"))
                if record["state"] != "running" and not record["delivered"]:
                    body = self._path(record["job_id"], record["owner"], ".log").read_bytes()
                    results.append((record, body))
            return sorted(results, key=lambda pair: pair[0]["started_at"])

    def acknowledge(self, job_id, *, owner):
        with self._guard():
            record = self._load(job_id, owner)
            record["delivered"] = True
            self._save(record)


def cleanup_expired_main(argv=None):
    """CLI entrypoint: print the cleanup count only and return nonzero on failure."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", default=None,
                        help="background-jobs directory; defaults below ORACLE_MESH_WORK_DIR")
    options = parser.parse_args(argv)
    directory = options.directory
    if not directory:
        work_dir = os.environ.get("ORACLE_MESH_WORK_DIR", "").strip()
        if not work_dir:
            return 2
        directory = str(Path(work_dir) / "background-jobs")
    try:
        removed = cleanup_expired_background_jobs(directory)
    except Exception:
        return 1
    print("claw_background_cleanup_files_removed=%d" % removed, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(cleanup_expired_main())
