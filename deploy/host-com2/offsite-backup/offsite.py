#!/usr/bin/env python3
"""#5093 — daily encrypted COM2 SQLite backups to Cloudflare R2, and restore.

Every service on COM2 already writes a verified daily snapshot with SQLite
`VACUUM INTO` (queue #6135, chat #6144, broker #6162). This tool copies the
newest one per service off the machine:

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
from typing import Any

ENDPOINT_ENV = "OFFSITE_R2_ENDPOINT"
BUCKET_ENV = "OFFSITE_R2_BUCKET"
TOKEN_ID_FILE_ENV = "OFFSITE_R2_TOKEN_ID_FILE"
TOKEN_SECRET_FILE_ENV = "OFFSITE_R2_TOKEN_SECRET_FILE"
KEY_FILE_ENV = "COM2_OFFSITE_KEY_FILE"
KEY_ID_ENV = "COM2_OFFSITE_KEY_ID"
R2_DIR_ENV = "OFFSITE_R2_DIR"  # local double for rehearsal; never set on COM2
STATE_DIR_ENV = "OFFSITE_STATE_DIR"
PREFIX = "offsite/v1"
MAX_AGE_HOURS = 26
RETRY_ATTEMPTS = 2

DEFAULT_SERVICES = {
    # service: (backups dir env, dir default, filename glob)
    "queue": ("OFFSITE_QUEUE_BACKUP_DIR", "/opt/padiem/backups/mesh-queue", "queue-*.sqlite"),
    "chat": ("OFFSITE_CHAT_BACKUP_DIR", "/mnt/d/padiem/chat-com2/backups", "chat-*.sqlite3"),
    "broker": ("OFFSITE_BROKER_BACKUP_DIR", "/mnt/d/padiem/broker/backups", "broker-*.sqlite3"),
}

__all__ = [
    "FileSystemR2", "S3R2Store", "main", "prune_prefix", "restore_generation",
    "run_upload",
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


def run_upload(
    env: dict[str, str], *, services: list[str] | None = None, now: datetime | None = None
) -> list[dict[str, Any]]:
    crypto = _load_crypto()
    key, key_id = load_key(env, crypto)
    store = _store_from_env(env)
    state_dir = Path(env.get(STATE_DIR_ENV, "/var/lib/padiem-offsite-backup"))
    state_dir.mkdir(parents=True, exist_ok=True)
    day = (now or _now()).strftime("%Y%m%d")
    results = []
    for service in services or list(DEFAULT_SERVICES):
        dir_env, default_dir, pattern = DEFAULT_SERVICES[service]
        directory = env.get(dir_env, "").strip() or default_dir
        source = _latest_backup(directory, pattern, max_age_hours=MAX_AGE_HOURS)
        plaintext = source.read_bytes()
        backup_id = day
        ciphertext = crypto.encrypt_payload(plaintext, key, key_id, service, backup_id)
        payload_key = f"{PREFIX}/{service}/daily/{backup_id}.cbe1"
        manifest = {
            "service": service,
            "backup_id": backup_id,
            "source_file": source.name,
            "plaintext_sha256": _sha256(plaintext),
            "ciphertext_sha256": _sha256(ciphertext),
            "bytes": len(ciphertext),
            "key_id": key_id,
            "created_at": _now().isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
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
        if (now or _now()).weekday() == 6:  # Sunday UTC
            week = (now or _now()).strftime("%Y-W%V")
            store.put(f"{PREFIX}/{service}/weekly/{week}.cbe1", ciphertext)
            store.put(_manifest_key(f"{PREFIX}/{service}/weekly/{week}.cbe1"), manifest_bytes)
            if store.get(f"{PREFIX}/{service}/weekly/{week}.cbe1") != ciphertext:
                raise OffsiteError("verify_mismatch_weekly")
            weekly_removed = prune_prefix(
                store, f"{PREFIX}/{service}/weekly/",
                int(env.get("OFFSITE_RETENTION_WEEKLY", "4")),
            )

        daily_removed = prune_prefix(
            store, f"{PREFIX}/{service}/daily/",
            int(env.get("OFFSITE_RETENTION_DAILY", "7")),
        )
        ledger = state_dir / "ledger.jsonl"
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "service": service, "backup_id": backup_id,
                "ciphertext_sha256": manifest["ciphertext_sha256"],
                "key_id": key_id, "at": manifest["created_at"],
            }, sort_keys=True) + "\n")
        os.chmod(ledger, 0o600)
        results.append({
            "service": service, "backup_id": backup_id, "bytes": len(ciphertext),
            "ciphertext_sha256": manifest["ciphertext_sha256"],
            "daily_pruned": len(daily_removed), "weekly_pruned": len(weekly_removed),
        })
    return results


# --- restore -----------------------------------------------------------------

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
    connection = sqlite3.connect(f"file:{staged}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        tables = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    finally:
        connection.close()
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
        "bytes": len(plaintext), "tables": int(tables),
        "staged": str(staged), "replaced": replaced,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    upload = sub.add_parser("upload")
    upload.add_argument("--service", action="append", choices=sorted(DEFAULT_SERVICES))

    restore = sub.add_parser("restore")
    restore.add_argument("--service", required=True, choices=sorted(DEFAULT_SERVICES))
    restore.add_argument("--date", default="")
    restore.add_argument("--weekly", default="")
    restore.add_argument("--target", default="")
    restore.add_argument("--replace", action="store_true")

    listing = sub.add_parser("list")
    listing.add_argument("--service", required=True, choices=sorted(DEFAULT_SERVICES))

    args = parser.parse_args(argv)
    env = dict(os.environ)
    try:
        if args.command == "upload":
            for result in run_upload(env, services=args.service):
                print(
                    "OFFSITE_UPLOAD=PASS service={service} backup={backup_id} bytes={bytes} "
                    "sha256={ciphertext_sha256} daily_pruned={daily_pruned} "
                    "weekly_pruned={weekly_pruned}".format(**result)
                )
            return 0
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
                "tables={tables} replaced={replaced} staged={staged}".format(**result)
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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
