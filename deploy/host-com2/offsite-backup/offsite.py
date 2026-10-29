#!/usr/bin/env python3
"""#5093 — daily encrypted COM2 SQLite backups to Cloudflare R2, and restore.

Every service on COM2 already writes a verified daily snapshot with SQLite
`VACUUM INTO` (queue #6135, chat #6144, broker #6162). This tool copies the
newest one per service off the machine:

* the two **D1 generations** are backed up too (`d1-chat`, `d1-engine`). Those are
  the real data: the 04:20 Windows task `PADIEM-COM2-D1-R2-Sync` publishes
  `storage-migration/snapshots/generations/<id>/{chat,engine}.sqlite3` and nothing
  but this tool takes them off the disk. Their source is resolved by the reviewed
  authority `scripts/ops/com2_backup_schedule.resolve_generation`, which re-hashes
  each seed against the published pointer before anything reads it, so a torn or
  half-published generation is never uploaded;
* encryption uses the SAME reviewed envelope as `scripts/ops/com2_backup.py`
  (PADIEM-CBE1, AES-256-GCM; AAD binds the service and backup id). The key file
  stays on COM2 (0600) and is NEVER uploaded — a stolen bucket without the key
  is ciphertext;
* after every upload the payload and manifest are downloaded again and their
  SHA-256 compared with what was sent; any mismatch fails the run;
* retention keeps N daily and M weekly generations (defaults 7 / 4). Weekly
  copies reuse the daily ciphertext under a weekly name; the manifest still
  carries the daily backup id, which is what the AAD was bound to;
* restore downloads, verifies the hash, decrypts, runs `PRAGMA integrity_check`
  and only then replaces a target file (the previous file is kept beside it).

Per-service status is reported, not averaged. A service that is not installed
(no unit file and no source path) is `NOT_INSTALLED`: reported, never a failure.
A service that IS installed but has no backup, or one older than
`MAX_AGE_HOURS`, is `FAIL`. `UNKNOWN` is never a success. The run exits non-zero
when any service is `FAIL`/`UNKNOWN` or when nothing at all was uploaded, so one
absent queue can no longer stop the D1 generations from being protected.

Nothing here decides cost or retention policy beyond the reviewed env values,
and nothing talks to a database that is running: the runbook stops the service
first. The R2 token is a bucket-scoped Object Read & Write token supplied as
0600 files; it is not created by this tool.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

ENDPOINT_ENV = "OFFSITE_R2_ENDPOINT"
BUCKET_ENV = "OFFSITE_R2_BUCKET"
TOKEN_ID_FILE_ENV = "OFFSITE_R2_TOKEN_ID_FILE"
TOKEN_SECRET_FILE_ENV = "OFFSITE_R2_TOKEN_SECRET_FILE"
KEY_FILE_ENV = "COM2_OFFSITE_KEY_FILE"
KEY_ID_ENV = "COM2_OFFSITE_KEY_ID"
R2_DIR_ENV = "OFFSITE_R2_DIR"  # local double for rehearsal; never set on COM2
STATE_DIR_ENV = "OFFSITE_STATE_DIR"
GENERATIONS_DIR_ENV = "OFFSITE_D1_GENERATIONS_DIR"
MOUNT_ROOT_ENV = "OFFSITE_D1_MOUNT_ROOT"
RUNTIME_POINTER_ENV = "OFFSITE_D1_RUNTIME_POINTER"
GENERATION_OPS_ENV = "OFFSITE_GENERATION_OPS_PATH"
PREFIX = "offsite/v1"
MAX_AGE_HOURS = 26
RETRY_ATTEMPTS = 2

#: systemd only keeps units in these directories; their presence is what says
#: "this service is installed here", as opposed to absent on this host.
UNIT_DIRS = ("/etc/systemd/system", "/run/systemd/system", "/usr/lib/systemd/system")

#: The published D1 generation id, as `refresh_d1.py` names it.
GENERATION_ID_FORMATS = ("%Y%m%dT%H%M%S%fZ", "%Y%m%dT%H%M%SZ")

STATUS_OK = "OK"
STATUS_FAIL = "FAIL"
STATUS_NOT_INSTALLED = "NOT_INSTALLED"
STATUS_UNKNOWN = "UNKNOWN"


class ServiceSource(NamedTuple):
    """Where one service's backupable SQLite lives, and how to tell it exists."""

    name: str
    kind: str  # "glob": newest file in a directory, "d1": the published generation
    dir_env: str = ""
    default_dir: str = ""
    pattern: str = ""
    label: str = ""  # d1 generations only: the seed name inside the generation
    units: tuple[str, ...] = ()  # systemd unit names that mean "installed on this host"


SERVICES: dict[str, ServiceSource] = {
    "queue": ServiceSource(
        "queue", "glob",
        "OFFSITE_QUEUE_BACKUP_DIR", "/opt/padiem/backups/mesh-queue", "queue-*.sqlite",
        units=("padiem-mesh-queue.service", "padiem-mesh-queue-backup.service"),
    ),
    "chat": ServiceSource(
        "chat", "glob",
        "OFFSITE_CHAT_BACKUP_DIR", "/mnt/d/padiem/chat-com2/backups", "chat-*.sqlite3",
        units=("padiem-chat-com2.service", "padiem-chat-com2-backup.service"),
    ),
    "broker": ServiceSource(
        "broker", "glob",
        "OFFSITE_BROKER_BACKUP_DIR", "/mnt/d/padiem/broker/backups", "broker-*.sqlite3",
        units=("padiem-broker.service", "padiem-broker-backup.service"),
    ),
    # The D1 pair is the data the COM2 disk holds nowhere else. Windows paths are
    # read through /mnt/<drive>, and only ever read.
    "d1-chat": ServiceSource("d1-chat", "d1", label="chat"),
    "d1-engine": ServiceSource("d1-engine", "d1", label="engine"),
}

__all__ = [
    "FileSystemR2", "S3R2Store", "main", "prune_prefix", "restore_generation",
    "rehearse", "run_outcome", "run_upload", "table_row_counts",
]


class OffsiteError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_crypto():
    """The reviewed envelope helpers from scripts/ops/com2_backup.py."""

    explicit = os.environ.get("OFFSITE_CRYPTO_PATH", "").strip()
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    candidates.append(Path(__file__).resolve().parents[3] / "scripts" / "ops" / "com2_backup.py")
    candidates.append(Path("/opt/padiem/offsite-backup/com2_backup.py"))
    for path in candidates:
        if path.is_file():
            spec = importlib.util.spec_from_file_location("com2_backup_crypto", path)
            module = importlib.util.module_from_spec(spec)
            # dataclasses resolve their module by name; register before exec.
            sys.modules.setdefault("com2_backup_crypto", module)
            spec.loader.exec_module(module)
            return module
    raise OffsiteError("crypto_module_missing")


def _read_secret_file(path_text: str, *, label: str) -> str:
    path = Path(path_text)
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise OffsiteError(f"{label}_unreadable") from exc
    if not value:
        raise OffsiteError(f"{label}_empty")
    return value


def load_key(env: dict[str, str], crypto) -> tuple[bytes, str]:
    raw = _read_secret_file(env.get(KEY_FILE_ENV, ""), label="key")
    key = crypto.parse_encryption_key(raw)
    key_id = str(env.get(KEY_ID_ENV, "")).strip() or crypto.validate_key_id(
        Path(env.get(KEY_FILE_ENV, "")).name.replace(".", "-")
    )
    crypto.validate_key_id(key_id)
    return key, key_id


# --- R2 transport ------------------------------------------------------------

class FileSystemR2:
    """The rehearsal double: same surface, a directory as the bucket."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.operations: list[tuple[str, str]] = []
        self._corrupt_on_read: set[str] = set()

    def _path(self, key: str) -> Path:
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root):
            raise OffsiteError("r2_key_escaped")
        return target

    def put(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        self.operations.append(("put", key))

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        if not path.is_file():
            return None
        data = path.read_bytes()
        self.operations.append(("get", key))
        if key in self._corrupt_on_read:
            return data[:-1] + bytes([data[-1] ^ 0xFF])
        return data

    def list(self, prefix: str) -> list[tuple[str, int]]:
        self.operations.append(("list", prefix))
        found = []
        for path in self.root.rglob("*"):
            if path.is_file():
                key = path.relative_to(self.root).as_posix()
                if key.startswith(prefix):
                    found.append((key, path.stat().st_size))
        return sorted(found)

    def delete(self, key: str) -> None:
        self.operations.append(("delete", key))
        self._path(key).unlink(missing_ok=True)

    def corrupt_on_read(self, key: str) -> None:
        self._corrupt_on_read.add(key)


class S3R2Store:
    """Cloudflare R2's S3 API with AWS SigV4 — no boto3, no extra dependency."""

    def __init__(self, endpoint: str, bucket: str, token_id: str, token_secret: str):
        parsed = urllib.parse.urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.hostname:
            raise OffsiteError("r2_endpoint_invalid")
        self.host = parsed.netloc
        self.base_path = parsed.path.rstrip("/")
        self.bucket = bucket
        self.token_id = token_id
        self.token_secret = token_secret

    @staticmethod
    def _hmac(key: bytes, message: str) -> bytes:
        return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

    def _signed_request(self, method: str, key: str, query: dict[str, str] | None = None,
                        body: bytes = b"") -> tuple[str, dict[str, str]]:
        now = _now()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        day = now.strftime("%Y%m%d")
        segments = [self.bucket] + (key.split("/") if key else [])
        canonical_uri = "/".join(
            urllib.parse.quote(part, safe="-_.~") for part in segments
        )
        uri = f"{self.base_path}/{canonical_uri}"
        items = sorted((query or {}).items())
        canonical_query = "&".join(
            f"{urllib.parse.quote(name, safe='-_.~')}={urllib.parse.quote(value, safe='-_.~')}"
            for name, value in items
        )
        payload_hash = _sha256(body)
        canonical_headers = (
            f"host:{self.host}\n"
            f"x-amz-content-sha256:{payload_hash}\n"
            f"x-amz-date:{amz_date}\n"
        )
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join(
            (method, uri, canonical_query, canonical_headers, signed_headers, payload_hash)
        )
        scope = f"{day}/auto/s3/aws4_request"
        string_to_sign = "\n".join(
            ("AWS4-HMAC-SHA256", amz_date, scope, _sha256(canonical_request.encode()))
        )
        key_date = self._hmac(("AWS4" + self.token_secret).encode(), day)
        key_region = self._hmac(key_date, "auto")
        key_service = self._hmac(key_region, "s3")
        signing = self._hmac(key_service, "aws4_request")
        signature = hmac.new(signing, string_to_sign.encode(), hashlib.sha256).hexdigest()
        authorization = (
            f"AWS4-HMAC-SHA256 Credential={self.token_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        url = f"https://{self.host}{uri}"
        if canonical_query:
            url += "?" + canonical_query
        headers = {
            "host": self.host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            "authorization": authorization,
        }
        return url, headers

    def _request(self, method: str, key: str, query=None, body=b"") -> tuple[int, bytes]:
        last: Exception | None = None
        for attempt in range(RETRY_ATTEMPTS):
            url, headers = self._signed_request(method, key, query, body)
            request = urllib.request.Request(url, data=body if method != "GET" else None,
                                             headers=headers, method=method)
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    return 404, b""
                if exc.code < 500 or attempt == RETRY_ATTEMPTS - 1:
                    raise OffsiteError(f"r2_status_{exc.code}") from None
                last = exc
            except (urllib.error.URLError, TimeoutError) as exc:
                last = exc
            time.sleep(1 + attempt)
        raise OffsiteError("r2_unreachable") from last

    def put(self, key: str, data: bytes) -> None:
        status, _ = self._request("PUT", key, body=data)
        if status not in (200, 201):
            raise OffsiteError(f"r2_put_status_{status}")

    def get(self, key: str) -> bytes | None:
        status, data = self._request("GET", key)
        return None if status == 404 else data

    def list(self, prefix: str) -> list[tuple[str, int]]:
        found: list[tuple[str, int]] = []
        token = ""
        while True:
            query = {"list-type": "2", "prefix": prefix, "max-keys": "1000"}
            if token:
                query["continuation-token"] = token
            status, data = self._request("GET", "", query)
            if status != 200:
                raise OffsiteError(f"r2_list_status_{status}")
            text = data.decode("utf-8", errors="replace")
            for block in text.split("<Contents>")[1:]:
                key = block.split("<Key>", 1)[1].split("</Key>", 1)[0]
                size = int(block.split("<Size>", 1)[1].split("</Size>", 1)[0])
                found.append((key, size))
            token = ""
            if "<IsTruncated>true</IsTruncated>" in text:
                token = text.split("<NextContinuationToken>", 1)[1].split(
                    "</NextContinuationToken>", 1
                )[0]
            else:
                return sorted(found)

    def delete(self, key: str) -> None:
        status, _ = self._request("DELETE", key)
        if status not in (200, 204):
            raise OffsiteError(f"r2_delete_status_{status}")


def _store_from_env(env: dict[str, str]) -> Any:
    double = env.get(R2_DIR_ENV, "").strip()
    if double:
        return FileSystemR2(double)
    endpoint = env.get(ENDPOINT_ENV, "").strip()
    bucket = env.get(BUCKET_ENV, "").strip()
    if not endpoint or not bucket:
        raise OffsiteError("r2_config_missing")
    token_id = _read_secret_file(env.get(TOKEN_ID_FILE_ENV, ""), label="r2_token_id")
    token_secret = _read_secret_file(env.get(TOKEN_SECRET_FILE_ENV, ""), label="r2_token_secret")
    return S3R2Store(endpoint, bucket, token_id, token_secret)


# --- upload ------------------------------------------------------------------

#: Where WSL sees the generation the 04:20 Windows task publishes. Read-only:
#: this tool never writes into a generation directory.
DEFAULT_GENERATIONS_DIR = (
    "/mnt/d/PADIEM-Servers/infrastructure/storage-migration/snapshots/generations"
)
#: Evidence that this host is the machine expected to hold the D1 pair: the Windows
#: drive is mounted. Absent drive is a NOT_INSTALLED report; a mounted drive with no
#: published generation is a FAIL, because that pair is the data we are protecting.
DEFAULT_D1_MOUNT_ROOT = "/mnt/d"


class SourceUnresolved(Exception):
    """One service's backupable file could not be named; carries its status."""

    def __init__(self, status: str, reason: str):
        super().__init__(reason)
        self.status = status
        self.reason = reason


def _latest_backup(directory: str, pattern: str, *, max_age_hours: int) -> Path:
    base = Path(directory)
    candidates = sorted(base.glob(pattern), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise OffsiteError(f"backup_missing:{base.name}")
    newest = candidates[-1]
    age = time.time() - newest.stat().st_mtime
    if age > max_age_hours * 3600:
        raise OffsiteError("backup_stale")
    return newest


def unit_present(names: tuple[str, ...], unit_dirs: tuple[str, ...] = UNIT_DIRS) -> bool:
    """True when systemd knows a unit of this name on this host."""
    for directory in unit_dirs:
        for name in names:
            if Path(directory, name).is_file():
                return True
    return False


def service_installed(
    source: ServiceSource, env: dict[str, str], *, unit_dirs: tuple[str, ...] = UNIT_DIRS
) -> bool:
    """Installed means this host has the service or its data location at all."""
    if source.kind == "d1":
        mount = env.get(MOUNT_ROOT_ENV, "").strip() or DEFAULT_D1_MOUNT_ROOT
        return bool(mount) and Path(mount).is_dir()
    directory = env.get(source.dir_env, "").strip() or source.default_dir
    return (bool(directory) and Path(directory).is_dir()) or unit_present(
        source.units, unit_dirs
    )


def generations_dir(env: dict[str, str]) -> Path:
    return Path(env.get(GENERATIONS_DIR_ENV, "").strip() or DEFAULT_GENERATIONS_DIR)


def _load_generation_ops(env: dict[str, str]):
    """The reviewed generation authority: scripts/ops/com2_backup_schedule.py.

    It re-hashes every seed against the published pointer before returning it, so
    a half-published generation cannot be handed to this tool as a backup source.
    """

    explicit = env.get(GENERATION_OPS_ENV, "").strip()
    if explicit:
        # An operator named the authority; if that file is not there, saying so is
        # the answer. Falling back to a different copy would hide a bad install.
        path = Path(explicit)
        if not path.is_file():
            raise OffsiteError("generation_ops_missing")
        return _import_generation_ops(path)
    for path in (
        Path(__file__).resolve().parents[3] / "scripts" / "ops" / "com2_backup_schedule.py",
        Path("/opt/padiem/offsite-backup/com2_backup_schedule.py"),
    ):
        if path.is_file():
            return _import_generation_ops(path)
    raise OffsiteError("generation_ops_missing")


def _import_generation_ops(path: Path):
    spec = importlib.util.spec_from_file_location("com2_backup_schedule_ops", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("com2_backup_schedule_ops", module)
    spec.loader.exec_module(module)
    return module


def _generation_captured(generation: str) -> datetime | None:
    for fmt in GENERATION_ID_FORMATS:
        try:
            return datetime.strptime(generation, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _resolve_generation(
    env: dict[str, str], *, max_age_hours: int, reference: datetime
) -> dict[str, Any]:
    """The published D1 generation, verified once and shared by both labels."""

    root = generations_dir(env)
    pointer = env.get(RUNTIME_POINTER_ENV, "").strip()
    ops = _load_generation_ops(env)
    # Only generations_dir steers the resolver; endpoint and key_id belong to the
    # schedule tool's own upload path, which this call never reaches.
    config = ops.BackupConfig(
        endpoint="offsite-resolve-only",
        key_id="offsite-resolve-only",
        generations_dir=root,
        generation_pointer=Path(pointer) if pointer else None,
    )
    try:
        resolved = ops.resolve_generation(config)
    except Exception as exc:  # the authority's own failure codes are the contract
        raise SourceUnresolved(STATUS_FAIL, f"generation:{exc}") from None
    if not isinstance(resolved, dict):
        raise SourceUnresolved(STATUS_FAIL, "generation:generation_config_incomplete")
    generation = str(resolved.get("generation") or "")
    captured = _generation_captured(generation)
    if captured is None:
        # A generation whose id is not an instant cannot be judged for freshness.
        raise SourceUnresolved(STATUS_UNKNOWN, f"generation_capture_unparsable:{generation}")
    age_hours = (reference - captured).total_seconds() / 3600
    if age_hours > max_age_hours:
        raise SourceUnresolved(STATUS_FAIL, f"generation_stale:{round(age_hours)}h")
    return {
        "generation": generation,
        "captured_utc": captured.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "snapshot": Path(resolved["snapshot"]),
        "databases": resolved["databases"],
    }


def _resolve_source(
    source: ServiceSource, env: dict[str, str], *, generation: dict[str, Any] | None,
    max_age_hours: int,
) -> tuple[Path, dict[str, Any]]:
    """Name the file this service's backup must carry, or raise SourceUnresolved."""
    if source.kind == "glob":
        directory = env.get(source.dir_env, "").strip() or source.default_dir
        try:
            path = _latest_backup(directory, source.pattern, max_age_hours=max_age_hours)
        except OffsiteError as exc:
            raise SourceUnresolved(STATUS_FAIL, str(exc)) from None
        return path, {"source_file": path.name}
    if generation is None:
        raise SourceUnresolved(STATUS_UNKNOWN, "generation_unresolved")
    record = generation["databases"].get(source.label)
    if not isinstance(record, dict):
        raise SourceUnresolved(STATUS_FAIL, f"generation_{source.label}_missing")
    path = generation["snapshot"] / record["file"]
    if not path.is_file():
        raise SourceUnresolved(STATUS_FAIL, f"generation_{source.label}_missing")
    return path, {
        "source_file": record["file"],
        "generation": generation["generation"],
        "captured_utc": generation["captured_utc"],
        "database": record["database"],
    }


def prune_prefix(store: Any, prefix: str, keep: int) -> list[str]:
    names = sorted(key for key, _size in store.list(prefix) if key.endswith(".cbe1"))
    removed: list[str] = []
    for key in names[:-keep] if keep > 0 else names:
        removed.append(key)
        store.delete(key)
        manifest = key[: -len(".cbe1")] + ".json"
        store.delete(manifest)
    return removed


def _manifest_key(payload_key: str) -> str:
    return payload_key[: -len(".cbe1")] + ".json"


def _upload_one(
    store: Any, crypto: Any, key: bytes, key_id: str, *, service: str, backup_id: str,
    path: Path, evidence: dict[str, Any], state_dir: Path, now: datetime | None,
    keep_daily: int, keep_weekly: int,
) -> dict[str, Any]:
    """One service's ciphertext, manifest, re-read verification, retention, ledger."""
    plaintext = path.read_bytes()
    ciphertext = crypto.encrypt_payload(plaintext, key, key_id, service, backup_id)
    payload_key = f"{PREFIX}/{service}/daily/{backup_id}.cbe1"
    manifest = {
        "service": service,
        "backup_id": backup_id,
        "source_file": evidence.get("source_file", path.name),
        "plaintext_sha256": _sha256(plaintext),
        "ciphertext_sha256": _sha256(ciphertext),
        "bytes": len(ciphertext),
        "key_id": key_id,
        "created_at": _now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
    }
    manifest.update({k: v for k, v in evidence.items() if k != "source_file"})
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    store.put(payload_key, ciphertext)
    store.put(_manifest_key(payload_key), manifest_bytes)

    remote_payload = store.get(payload_key)
    remote_manifest = store.get(_manifest_key(payload_key))
    if remote_payload is None or _sha256(remote_payload) != manifest["ciphertext_sha256"]:
        raise OffsiteError("verify_mismatch_payload")
    if remote_manifest != manifest_bytes:
        raise OffsiteError("verify_mismatch_manifest")

    weekly_removed: list[str] = []
    stamp = now or _now()
    if stamp.weekday() == 6:  # Sunday UTC
        week = stamp.strftime("%Y-W%V")
        store.put(f"{PREFIX}/{service}/weekly/{week}.cbe1", ciphertext)
        store.put(_manifest_key(f"{PREFIX}/{service}/weekly/{week}.cbe1"), manifest_bytes)
        if store.get(f"{PREFIX}/{service}/weekly/{week}.cbe1") != ciphertext:
            raise OffsiteError("verify_mismatch_weekly")
        weekly_removed = prune_prefix(store, f"{PREFIX}/{service}/weekly/", keep_weekly)

    daily_removed = prune_prefix(store, f"{PREFIX}/{service}/daily/", keep_daily)
    ledger = state_dir / "ledger.jsonl"
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "service": service, "backup_id": backup_id,
            "ciphertext_sha256": manifest["ciphertext_sha256"],
            "key_id": key_id, "at": manifest["created_at"],
        }, sort_keys=True) + "\n")
    os.chmod(ledger, 0o600)
    return {
        "service": service, "status": STATUS_OK, "backup_id": backup_id,
        "source_file": manifest["source_file"], "bytes": len(ciphertext),
        "plaintext_sha256": manifest["plaintext_sha256"],
        "ciphertext_sha256": manifest["ciphertext_sha256"],
        "generation": evidence.get("generation"),
        "daily_pruned": len(daily_removed), "weekly_pruned": len(weekly_removed),
    }


def run_upload(
    env: dict[str, str], *, services: list[str] | None = None, now: datetime | None = None,
    unit_dirs: tuple[str, ...] = UNIT_DIRS,
) -> list[dict[str, Any]]:
    """Every requested service is judged; the healthy ones are then uploaded.

    Classifying first is what lets one absent queue report its own status without
    deciding the fate of the D1 generations. A failure of *our* write (store, key,
    verification) still aborts the run, because then nothing stored is trustable.
    """
    requested = list(dict.fromkeys(services or list(SERVICES)))
    unknown = [name for name in requested if name not in SERVICES]
    if unknown:
        raise OffsiteError("service_unknown:" + ",".join(unknown))

    crypto = _load_crypto()
    key, key_id = load_key(env, crypto)
    store = _store_from_env(env)
    state_dir = Path(env.get(STATE_DIR_ENV, "/var/lib/padiem-offsite-backup"))
    state_dir.mkdir(parents=True, exist_ok=True)
    backup_id = (now or _now()).strftime("%Y%m%d")
    keep_daily = int(env.get("OFFSITE_RETENTION_DAILY", "7"))
    keep_weekly = int(env.get("OFFSITE_RETENTION_WEEKLY", "4"))

    generation: dict[str, Any] | None = None
    generation_error: SourceUnresolved | None = None
    if any(SERVICES[name].kind == "d1" and service_installed(SERVICES[name], env, unit_dirs=unit_dirs)
           for name in requested):
        try:
            generation = _resolve_generation(
                env, max_age_hours=MAX_AGE_HOURS, reference=now or _now()
            )
        except SourceUnresolved as exc:
            generation_error = exc
        except OffsiteError as exc:
            # The authority itself is not deployed. That is the two generation
            # targets' failure, reported as such — the SQLite services on the same
            # disk still get their copy off the machine.
            generation_error = SourceUnresolved(STATUS_FAIL, str(exc))

    rows: dict[str, dict[str, Any]] = {}
    ready: list[tuple[ServiceSource, Path, dict[str, Any]]] = []
    for name in requested:
        source = SERVICES[name]
        if not service_installed(source, env, unit_dirs=unit_dirs):
            rows[name] = {
                "service": name, "status": STATUS_NOT_INSTALLED,
                "reason": "unit_and_path_absent" if source.kind == "glob" else "path_absent",
            }
            continue
        if source.kind == "d1" and generation_error is not None:
            rows[name] = {"service": name, "status": generation_error.status,
                          "reason": generation_error.reason}
            continue
        try:
            path, evidence = _resolve_source(
                source, env, generation=generation, max_age_hours=MAX_AGE_HOURS
            )
        except SourceUnresolved as exc:
            rows[name] = {"service": name, "status": exc.status, "reason": exc.reason}
            continue
        ready.append((source, path, evidence))

    for source, path, evidence in ready:
        rows[source.name] = _upload_one(
            store, crypto, key, key_id, service=source.name, backup_id=backup_id,
            path=path, evidence=evidence, state_dir=state_dir, now=now,
            keep_daily=keep_daily, keep_weekly=keep_weekly,
        )
    return [rows[name] for name in requested]


def run_outcome(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """FAIL or UNKNOWN anywhere fails the run; a run that uploaded nothing is not a pass."""
    failed = sorted(r["service"] for r in rows if r["status"] in (STATUS_FAIL, STATUS_UNKNOWN))
    uploaded = [r["service"] for r in rows if r["status"] == STATUS_OK]
    if failed:
        return {"status": "FAIL", "failed": failed, "uploaded": len(uploaded)}
    if not uploaded:
        return {
            "status": "UNKNOWN", "failed": ["no_service_produced_a_backup"],
            "uploaded": 0,
        }
    return {"status": "PASS", "failed": [], "uploaded": len(uploaded)}


# --- restore -----------------------------------------------------------------

def table_row_counts(path: Path) -> dict[str, int]:
    """Per-table row counts of a SQLite file, read-only. Views are not tables."""
    counts: dict[str, int] = {}
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        names = [
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            counts[name] = connection.execute(
                f"SELECT COUNT(*) FROM {quoted}"
            ).fetchone()[0]
    finally:
        connection.close()
    return counts


def _verify_staged(staged: Path) -> tuple[str, int, int]:
    connection = sqlite3.connect(f"file:{staged.as_posix()}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    counts = table_row_counts(staged)
    return str(integrity), len(counts), sum(counts.values())


def restore_generation(
    env: dict[str, str], *, service: str, backup_id: str, weekly_week: str | None,
    target: Path | None, replace: bool,
) -> dict[str, Any]:
    crypto = _load_crypto()
    key, key_id = load_key(env, crypto)
    store = _store_from_env(env)
    folder = f"{PREFIX}/{service}/weekly/{weekly_week}.cbe1" if weekly_week else \
        f"{PREFIX}/{service}/daily/{backup_id}.cbe1"
    ciphertext = store.get(folder)
    manifest_bytes = store.get(_manifest_key(folder))
    if ciphertext is None or manifest_bytes is None:
        raise OffsiteError("restore_object_missing")
    manifest = json.loads(manifest_bytes)
    if _sha256(ciphertext) != manifest.get("ciphertext_sha256"):
        raise OffsiteError("restore_hash_mismatch")
    if manifest.get("key_id") != key_id:
        raise OffsiteError("restore_key_id_mismatch")
    plaintext, _used_key = crypto.decrypt_payload(
        ciphertext, key, service, manifest["backup_id"], expected_key_id=key_id,
    )
    if _sha256(plaintext) != manifest.get("plaintext_sha256"):
        raise OffsiteError("restore_plaintext_mismatch")

    staging = Path(env.get(STATE_DIR_ENV, "/var/lib/padiem-offsite-backup")) / "restore"
    staging.mkdir(parents=True, exist_ok=True)
    staged = staging / f"{service}-{manifest['backup_id']}.sqlite3"
    staged.write_bytes(plaintext)
    os.chmod(staged, 0o600)
    integrity, tables, rows = _verify_staged(staged)
    if integrity != "ok":
        raise OffsiteError("restore_integrity_failed")
    replaced = False
    if replace:
        if target is None:
            raise OffsiteError("restore_target_required")
        if target.is_file():
            backup = target.with_name(f"{target.name}.pre-restore-{_now():%Y%m%dT%H%M%SZ}")
            target.replace(backup)
        target.write_bytes(staged.read_bytes())
        os.chmod(target, 0o600)
        replaced = True
    return {
        "service": service, "backup_id": manifest["backup_id"],
        "bytes": len(plaintext), "tables": int(tables), "rows": int(rows),
        "source_file": manifest.get("source_file"), "generation": manifest.get("generation"),
        "plaintext_sha256": manifest.get("plaintext_sha256"),
        "staged": str(staged), "replaced": replaced,
    }


def rehearse(env: dict[str, str], *, service: str, now: datetime | None = None) -> dict[str, Any]:
    """Upload one real source, bring it back, and prove what came back is that file.

    Local double only: the rehearsal must never be the reason a production bucket
    gains an object, so `OFFSITE_R2_DIR` (the directory-backed store) is required.
    """
    if not env.get(R2_DIR_ENV, "").strip():
        raise OffsiteError("rehearse_requires_local_bucket")
    source = SERVICES[service]
    generation = (
        _resolve_generation(
            env, max_age_hours=MAX_AGE_HOURS, reference=now or _now()
        )
        if source.kind == "d1"
        else None
    )
    path, evidence = _resolve_source(
        source, env, generation=generation, max_age_hours=MAX_AGE_HOURS
    )
    rows = run_upload(env, services=[service], now=now)
    row = rows[0]
    if row["status"] != STATUS_OK:
        raise OffsiteError(f"rehearse_upload_{row['status'].lower()}:{row.get('reason')}")
    restored = restore_generation(
        env, service=service, backup_id=row["backup_id"], weekly_week=None,
        target=None, replace=False,
    )
    source_counts = table_row_counts(path)
    restored_counts = table_row_counts(Path(restored["staged"]))
    source_sha = _sha256(path.read_bytes())
    if restored_counts != source_counts:
        difference = {
            name: (source_counts.get(name), restored_counts.get(name))
            for name in set(source_counts) | set(restored_counts)
            if source_counts.get(name) != restored_counts.get(name)
        }
        raise OffsiteError(f"rehearse_rows_mismatch:{sorted(difference)}")
    if restored["plaintext_sha256"] != source_sha:
        raise OffsiteError("rehearse_source_sha_mismatch")
    return {
        "service": service, "backup_id": row["backup_id"], "source_file": evidence["source_file"],
        "generation": evidence.get("generation"), "bytes": row["bytes"],
        "tables": len(source_counts), "rows": sum(source_counts.values()),
        "integrity": "ok", "plaintext_sha256": source_sha,
        "staged": restored["staged"],
    }


def _format_row(row: dict[str, Any]) -> str:
    parts = [f"OFFSITE_SERVICE={row['service']}", f"STATUS={row['status']}"]
    for label, field in (
        ("REASON", "reason"), ("BACKUP", "backup_id"), ("SOURCE", "source_file"),
        ("GENERATION", "generation"), ("BYTES", "bytes"), ("SHA256", "ciphertext_sha256"),
        ("DAILY_PRUNED", "daily_pruned"), ("WEEKLY_PRUNED", "weekly_pruned"),
    ):
        value = row.get(field)
        if value is not None:
            parts.append(f"{label}={value}")
    return " ".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    names = sorted(SERVICES)

    upload = sub.add_parser("upload")
    upload.add_argument("--service", action="append", choices=names)

    restore = sub.add_parser("restore")
    restore.add_argument("--service", required=True, choices=names)
    restore.add_argument("--date", default="")
    restore.add_argument("--weekly", default="")
    restore.add_argument("--target", default="")
    restore.add_argument("--replace", action="store_true")

    listing = sub.add_parser("list")
    listing.add_argument("--service", required=True, choices=names)

    # Local double only: prove a stored generation can be brought back and read.
    rehearsal = sub.add_parser("rehearse")
    rehearsal.add_argument("--service", required=True, choices=names)

    args = parser.parse_args(argv)
    env = dict(os.environ)
    try:
        if args.command == "upload":
            rows = run_upload(env, services=args.service)
            for row in rows:
                print(_format_row(row))
            outcome = run_outcome(rows)
            failed = ",".join(outcome["failed"]) or "-"
            print(
                f"OFFSITE_RUN={outcome['status']} UPLOADED={outcome['uploaded']} FAILED={failed}"
            )
            return 0 if outcome["status"] == "PASS" else 3
        if args.command == "restore":
            if not args.date and not args.weekly:
                raise OffsiteError("restore_date_or_weekly_required")
            result = restore_generation(
                env, service=args.service, backup_id=args.date,
                weekly_week=args.weekly or None,
                target=Path(args.target) if args.target else None,
                replace=args.replace,
            )
            print(
                "OFFSITE_RESTORE=PASS service={service} backup={backup_id} bytes={bytes} "
                "tables={tables} rows={rows} replaced={replaced} staged={staged}".format(**result)
            )
            return 0
        if args.command == "rehearse":
            result = rehearse(env, service=args.service)
            print(
                "OFFSITE_REHEARSAL=PASS service={service} backup={backup_id} "
                "source={source_file} generation={generation} bytes={bytes} tables={tables} "
                "rows={rows} integrity={integrity} sha256={plaintext_sha256} "
                "staged={staged}".format(**result)
            )
            return 0
        if args.command == "list":
            store = _store_from_env(env)
            for prefix in (f"{PREFIX}/{args.service}/daily/", f"{PREFIX}/{args.service}/weekly/"):
                for key, size in store.list(prefix):
                    print(f"OFFSITE_OBJECT={key} BYTES={size}")
            return 0
    except OffsiteError as exc:
        print(f"OFFSITE_FAILED reason={exc}")
        return 3
    except SourceUnresolved as exc:
        print(f"OFFSITE_FAILED reason={exc.reason}")
        return 3
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
