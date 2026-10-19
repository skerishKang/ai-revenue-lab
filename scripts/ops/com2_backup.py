#!/usr/bin/env python3
"""COM2 backup inventory, upload, verification and restore-check.

This is the operator side of the #5093 slice. It reuses the Worker contract in
``apps/com2-backup/backup_contract.py`` so the client and the Worker cannot drift
on route names, key layout, checksum rules or manifest shape.

Safety boundaries
-----------------
* ``inventory`` and ``backup`` only read source files. They never delete, move or
  rewrite anything under a source root.
* Secret-like paths and files carrying a high-confidence credential marker are
  excluded from the archive. Counts are reported; contents and values are never
  printed.
* ``restore-check`` verifies the downloaded archive, extracts it into a staging
  directory, verifies every file, and only then publishes into an explicitly
  supplied empty target. It never writes into a source root or a database.
* No retention, storage-class or cost policy is decided here.

Usage
-----
    python scripts/ops/com2_backup.py inventory
    python scripts/ops/com2_backup.py backup --out-dir build/com2-backup
    python scripts/ops/com2_backup.py upload --endpoint https://... --dir ...
    python scripts/ops/com2_backup.py verify --endpoint https://... --machine com2 --backup-id ...
    python scripts/ops/com2_backup.py restore-check --endpoint https://... --machine com2 --backup-id ... --target empty-dir

The bearer token is read from ``COM2_BACKUP_WRITE_TOKEN`` (override with
``--token-env``) and is never printed, logged or placed in a URL.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable

INVENTORY_KIND = "PADIEM_COM2_INVENTORY_V1"
DEFAULT_TOKEN_ENV = "COM2_BACKUP_WRITE_TOKEN"
HASH_CHUNK = 1024 * 1024
#: Decompressed-size guard for a restore check. This is a memory/disk safety
#: bound, not a retention or storage policy.
MAX_RESTORE_UNCOMPRESSED_BYTES = 256 * 1024 * 1024

_EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".wrangler",
    ".worker-src",
}
_SECRET_DIRS = {
    ".aws",
    ".gnupg",
    ".ssh",
    "credential",
    "credentials",
    "secret",
    "secrets",
}
_SECRET_FILE_NAMES = {
    ".env",
    ".netrc",
    ".npmrc",
    ".pgpass",
    "id_rsa",
    "id_ed25519",
    "known_hosts",
}
_SECRET_SUFFIXES = (".dpapi", ".key", ".kdbx", ".p12", ".pem", ".pfx")
_SECRET_NAME_TOKENS = (
    "api_key",
    "apikey",
    "cookie",
    "credential",
    "password",
    "passwd",
    "private_key",
    "secret",
    "token",
)
_SECRET_CONTENT_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"""(?i)\b(password|passwd|secret|token|api[_-]?key|client[_-]?secret|authorization)\b"""
        r"""['"]?\s*[:=]\s*['"]?[A-Za-z0-9_\-./+=]{8,}"""
    ),
)
_MAX_CONTENT_SCAN_BYTES = 256 * 1024


class OpsError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _load_contract():
    path = Path(__file__).resolve().parents[2] / "apps" / "com2-backup" / "backup_contract.py"
    spec = importlib.util.spec_from_file_location("com2_backup_contract", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("COM2_BACKUP_CONTRACT_NOT_FOUND")
    module = importlib.util.module_from_spec(spec)
    # Register before execution: dataclasses resolves the defining module via
    # ``sys.modules`` while processing the class.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CONTRACT = _load_contract()


@dataclass(frozen=True)
class SourceFile:
    arcname: str
    path: Path
    bytes: int
    sha256: str
    mtime: str


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def default_backup_id(moment: datetime | None = None) -> str:
    stamp = moment or datetime.now(timezone.utc)
    return stamp.strftime("%Y%m%dt%H%M%Sz")


def default_roots() -> list[Path]:
    """COM2 PADIEM data/settings roots, never a Git working copy."""
    roots: list[Path] = []
    for env_name in ("LOCALAPPDATA", "APPDATA"):
        base = os.environ.get(env_name)
        if not base:
            continue
        candidate = Path(base) / "PADIEM"
        if candidate.is_dir():
            roots.append(candidate)
    return roots


def _is_secret_like(relative: PurePosixPath) -> bool:
    lowered_parts = [part.lower() for part in relative.parts]
    if any(part in _SECRET_DIRS for part in lowered_parts[:-1]):
        return True
    name = lowered_parts[-1] if lowered_parts else ""
    if name in _SECRET_FILE_NAMES or name.startswith(".env."):
        return True
    if name.endswith(_SECRET_SUFFIXES):
        return True
    return any(token in name for token in _SECRET_NAME_TOKENS)


def _contains_secret_marker(path: Path) -> bool:
    """Conservative content scan; the value is never returned or logged."""
    try:
        with open(path, "rb") as handle:
            raw = handle.read(_MAX_CONTENT_SCAN_BYTES)
    except OSError:
        return True
    if b"\x00" in raw:
        return False
    text = raw.decode("utf-8", errors="ignore")
    return any(pattern.search(text) for pattern in _SECRET_CONTENT_PATTERNS)


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(HASH_CHUNK)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    """True for a symlink or a Windows junction/reparse point.

    A junction into a shared dependency directory must never be traversed by a
    backup walk (the repository operating policy calls this out explicitly).
    """
    if path.is_symlink():
        return True
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _non_overlapping_roots(roots: Iterable[Path]) -> list[Path]:
    resolved: list[Path] = []
    for root in roots:
        try:
            candidate = root.resolve()
        except OSError:
            continue
        if not candidate.is_dir():
            continue
        if any(
            candidate == existing or existing in candidate.parents
            for existing in resolved
        ):
            continue
        resolved.append(candidate)
    return resolved


def collect_files(roots: Iterable[Path]) -> tuple[list[SourceFile], dict, list[Path]]:
    """Read-only walk. Returns safe files, exclusion counts and root labels."""
    unique_roots = _non_overlapping_roots(roots)
    exclusions = {
        "secret_paths": 0,
        "secret_content": 0,
        "symlinks": 0,
        "non_regular": 0,
        "excluded_directories": 0,
    }
    files: list[SourceFile] = []
    for index, root in enumerate(unique_roots, start=1):
        label = f"root-{index}"
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            kept_dirs = []
            for name in sorted(dirnames):
                lowered = name.lower()
                full = Path(dirpath) / name
                if lowered in _EXCLUDED_DIRS or lowered in _SECRET_DIRS:
                    exclusions["excluded_directories"] += 1
                    continue
                if _is_reparse_point(full):
                    exclusions["symlinks"] += 1
                    continue
                kept_dirs.append(name)
            dirnames[:] = kept_dirs

            for name in sorted(filenames):
                full = Path(dirpath) / name
                try:
                    relative = full.relative_to(root)
                except ValueError:
                    continue
                if _is_reparse_point(full):
                    exclusions["symlinks"] += 1
                    continue
                try:
                    stat_result = full.stat(follow_symlinks=False)
                except OSError:
                    exclusions["non_regular"] += 1
                    continue
                if not stat.S_ISREG(stat_result.st_mode):
                    exclusions["non_regular"] += 1
                    continue
                posix_relative = PurePosixPath(relative.as_posix())
                if _is_secret_like(posix_relative):
                    exclusions["secret_paths"] += 1
                    continue
                if _contains_secret_marker(full):
                    exclusions["secret_content"] += 1
                    continue
                try:
                    size, digest = _hash_file(full)
                except OSError:
                    exclusions["non_regular"] += 1
                    continue
                arcname = f"{label}/{posix_relative.as_posix()}"
                mtime = datetime.fromtimestamp(
                    stat_result.st_mtime, timezone.utc
                ).strftime("%Y-%m-%dT%H:%M:%SZ")
                files.append(SourceFile(arcname, full, size, digest, mtime))

    files.sort(key=lambda item: item.arcname)
    if len(files) > CONTRACT.MAX_MANIFEST_FILES:
        raise OpsError("inventory_file_limit")
    return files, exclusions, unique_roots


def build_inventory(roots: Iterable[Path]) -> dict:
    files, exclusions, unique_roots = collect_files(roots)
    return {
        "kind": INVENTORY_KIND,
        "generated_at": _utc_now(),
        "roots": [
            {"id": f"root-{index}", "path": str(root)}
            for index, root in enumerate(unique_roots, start=1)
        ],
        "files": [
            {
                "path": item.arcname,
                "bytes": item.bytes,
                "sha256": item.sha256,
                "mtime": item.mtime,
            }
            for item in files
        ],
        "file_count": len(files),
        "total_bytes": sum(item.bytes for item in files),
        "excluded": exclusions,
    }


class _HashingReader:
    """Hash bytes as tarfile consumes them, so a mid-backup change is caught."""

    def __init__(self, handle):
        self._handle = handle
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        data = self._handle.read(size)
        if data:
            self.digest.update(data)
        return data


def _write_archive(files: list[SourceFile], destination: Path) -> None:
    with open(destination, "wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            with tarfile.open(
                fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT
            ) as archive:
                for item in files:
                    info = tarfile.TarInfo(item.arcname)
                    info.size = item.bytes
                    info.mtime = 0
                    info.mode = 0o600
                    info.uid = 0
                    info.gid = 0
                    info.uname = ""
                    info.gname = ""
                    with open(item.path, "rb") as source:
                        reader = _HashingReader(source)
                        archive.addfile(info, reader)
                    if reader.digest.hexdigest() != item.sha256:
                        raise OpsError("source_changed_during_backup")


def build_backup(
    roots: Iterable[Path],
    out_dir: Path,
    machine: str,
    backup_id: str,
    created_at: str,
) -> dict:
    CONTRACT.validate_machine(machine)
    CONTRACT.validate_backup_id(backup_id)
    files, exclusions, _ = collect_files(roots)
    if not files:
        raise OpsError("no_source_files")
    if sum(item.bytes for item in files) > MAX_RESTORE_UNCOMPRESSED_BYTES:
        # Keep the producible backup inside the restore-check safety bound.
        raise OpsError("source_size_limit")
    out_dir.mkdir(parents=True, exist_ok=True)
    payload_path = out_dir / "payload.tar.gz"
    temporary_payload = out_dir / "payload.tar.gz.part"
    if temporary_payload.exists():
        temporary_payload.unlink()
    try:
        _write_archive(files, temporary_payload)
        payload_bytes, payload_sha = _hash_file(temporary_payload)
        if payload_bytes > CONTRACT.MAX_PAYLOAD_BYTES:
            raise OpsError("payload_exceeds_transfer_bound")
        os.replace(temporary_payload, payload_path)
    finally:
        if temporary_payload.exists():
            temporary_payload.unlink()

    manifest = {
        "kind": CONTRACT.MANIFEST_KIND,
        "contract_version": CONTRACT.CONTRACT_VERSION,
        "machine": machine,
        "backup_id": backup_id,
        "created_at": created_at,
        "payload_file": "payload.tar.gz",
        "payload_bytes": payload_bytes,
        "payload_sha256": payload_sha,
        "file_count": len(files),
        "total_bytes": sum(item.bytes for item in files),
        "files": [
            {"path": item.arcname, "bytes": item.bytes, "sha256": item.sha256}
            for item in files
        ],
        "exclusions": exclusions,
    }
    CONTRACT.validate_manifest(manifest, machine, backup_id)
    manifest_path = out_dir / "manifest.json"
    temporary_manifest = out_dir / "manifest.json.part"
    temporary_manifest.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(temporary_manifest, manifest_path)
    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "payload_path": payload_path,
        "payload_bytes": payload_bytes,
        "payload_sha256": payload_sha,
    }


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never forward the bearer token to a redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _validate_endpoint(endpoint: str) -> str:
    parsed = urllib.parse.urlsplit(endpoint)
    if not parsed.hostname:
        raise OpsError("endpoint_invalid")
    if parsed.scheme == "https":
        return endpoint.rstrip("/")
    # Plain HTTP is accepted only for a loopback test server. This is a
    # transport-safety check, not a production deployment option.
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}:
        return endpoint.rstrip("/")
    raise OpsError("endpoint_requires_https")


def _token_from_env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise OpsError("backup_token_env_missing")
    return value


def _route_url(endpoint: str, machine: str, backup_id: str, action: str) -> str:
    machine = CONTRACT.validate_machine(machine)
    backup_id = CONTRACT.validate_backup_id(backup_id)
    return f"{endpoint}{CONTRACT.ROUTE_PREFIX}/{machine}/{backup_id}/{action}"


def _http(
    method: str,
    url: str,
    token: str,
    *,
    data: bytes | None = None,
    headers: dict | None = None,
    timeout: int = 120,
    max_response: int = CONTRACT.MAX_MANIFEST_BYTES,
) -> tuple[int, bytes]:
    request_headers = {"Authorization": f"Bearer {token}"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url, data=data, method=method, headers=request_headers
    )
    try:
        with _OPENER.open(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or 0)
            body = response.read(max_response + 1)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
        try:
            body = exc.read(max_response + 1)
        except Exception:
            body = b""
    except Exception:
        raise OpsError("endpoint_unreachable")
    if len(body) > max_response:
        raise OpsError("response_too_large")
    return status, body


def _error_code(status: int, body: bytes) -> str:
    try:
        parsed = json.loads(body.decode("utf-8"))
        code = parsed.get("error", {}).get("code")
        if isinstance(code, str) and code:
            return code
    except Exception:
        pass
    return f"http_{status}"


def _expect(status: int, body: bytes, allowed=(200,)) -> None:
    if status not in allowed:
        raise OpsError(_error_code(status, body))


def upload_backup(endpoint: str, directory: Path, machine: str, backup_id: str, token: str) -> dict:
    manifest_path = directory / "manifest.json"
    try:
        raw_manifest = manifest_path.read_bytes()
        manifest = CONTRACT.parse_manifest_bytes(raw_manifest, machine, backup_id)
    except FileNotFoundError:
        raise OpsError("manifest_missing")
    except CONTRACT.BackupError:
        raise OpsError("manifest_invalid")
    payload_path = directory / manifest["payload_file"]
    try:
        payload = payload_path.read_bytes()
    except FileNotFoundError:
        raise OpsError("payload_missing")
    if len(payload) > CONTRACT.MAX_PAYLOAD_BYTES:
        raise OpsError("payload_exceeds_transfer_bound")
    actual_sha = hashlib.sha256(payload).hexdigest()
    if actual_sha != manifest["payload_sha256"] or len(payload) != manifest["payload_bytes"]:
        raise OpsError("local_integrity_mismatch")

    status, body = _http(
        "PUT",
        _route_url(endpoint, machine, backup_id, CONTRACT.ARTIFACT_PAYLOAD),
        token,
        data=payload,
        headers={
            "Content-Type": "application/gzip",
            "X-Padiem-Content-Sha256": actual_sha,
        },
        max_response=CONTRACT.MAX_MANIFEST_BYTES,
    )
    _expect(status, body)

    status, body = _http(
        "PUT",
        _route_url(endpoint, machine, backup_id, CONTRACT.ARTIFACT_MANIFEST),
        token,
        data=raw_manifest,
        headers={"Content-Type": "application/json"},
    )
    _expect(status, body)

    status, body = _http(
        "POST",
        _route_url(endpoint, machine, backup_id, CONTRACT.ARTIFACT_VERIFY),
        token,
        data=b"",
        headers={"Content-Type": "application/json"},
    )
    _expect(status, body)
    try:
        verified = json.loads(body.decode("utf-8"))
    except Exception:
        raise OpsError("verify_response_invalid")
    if verified.get("result") != "verified":
        raise OpsError("integrity_mismatch")
    return {
        "payload_bytes": len(payload),
        "payload_sha256": actual_sha,
        "file_count": manifest["file_count"],
    }


def verify_backup(
    endpoint: str,
    machine: str,
    backup_id: str,
    token: str,
    local_dir: Path | None = None,
) -> dict:
    status, manifest_raw = _http(
        "GET",
        _route_url(endpoint, machine, backup_id, CONTRACT.ARTIFACT_MANIFEST),
        token,
    )
    _expect(status, manifest_raw)
    try:
        manifest = CONTRACT.parse_manifest_bytes(manifest_raw, machine, backup_id)
    except CONTRACT.BackupError:
        raise OpsError("manifest_invalid")

    status, payload = _http(
        "GET",
        _route_url(endpoint, machine, backup_id, CONTRACT.ARTIFACT_PAYLOAD),
        token,
        max_response=CONTRACT.MAX_PAYLOAD_BYTES,
    )
    _expect(status, payload)
    try:
        result = CONTRACT.integrity_result(manifest, payload)
    except CONTRACT.BackupError:
        raise OpsError("integrity_mismatch")

    if local_dir is not None:
        try:
            local_manifest = (local_dir / "manifest.json").read_bytes()
            local_payload = (local_dir / manifest["payload_file"]).read_bytes()
        except OSError:
            raise OpsError("local_backup_missing")
        if local_manifest != manifest_raw:
            raise OpsError("local_remote_manifest_differs")
        if hashlib.sha256(local_payload).hexdigest() != result["sha256"]:
            raise OpsError("local_remote_payload_differs")
    return result


# ---------------------------------------------------------------------------
# Restoration
# ---------------------------------------------------------------------------


def _safe_member_name(name: object) -> PurePosixPath:
    if not isinstance(name, str) or not name:
        raise OpsError("unsafe_archive_member")
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise OpsError("unsafe_archive_member")
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise OpsError("unsafe_archive_member")
    return PurePosixPath(*parts)


def extract_and_verify(payload_path: Path, staging: Path, manifest: dict) -> dict:
    """Extract into staging, then verify every member against the manifest."""
    staging.mkdir(parents=True, exist_ok=True)
    extracted: dict[str, dict] = {}
    total = 0
    try:
        with tarfile.open(payload_path, "r:gz") as archive:
            members = archive.getmembers()
            if len(members) > CONTRACT.MAX_MANIFEST_FILES:
                raise OpsError("archive_member_limit")
            for member in members:
                relative = _safe_member_name(member.name)
                if member.isdir():
                    continue
                if not member.isfile():
                    raise OpsError("unsafe_archive_member")
                key = relative.as_posix()
                if key in extracted:
                    raise OpsError("duplicate_archive_member")
                if member.size < 0 or total + member.size > MAX_RESTORE_UNCOMPRESSED_BYTES:
                    raise OpsError("restore_size_limit")
                total += member.size
                source = archive.extractfile(member)
                if source is None:
                    raise OpsError("archive_member_unreadable")
                destination = staging.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                written = 0
                with source, open(destination, "wb") as target:
                    while True:
                        chunk = source.read(HASH_CHUNK)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > member.size:
                            raise OpsError("archive_member_size_mismatch")
                        digest.update(chunk)
                        target.write(chunk)
                if written != member.size:
                    raise OpsError("archive_member_size_mismatch")
                extracted[key] = {"bytes": written, "sha256": digest.hexdigest()}
    except tarfile.TarError:
        raise OpsError("archive_invalid")
    except OSError:
        raise OpsError("archive_unreadable")

    expected = {entry["path"]: entry for entry in manifest["files"]}
    if set(extracted) != set(expected):
        raise OpsError("manifest_file_set_mismatch")
    for path, recorded in expected.items():
        actual = extracted[path]
        if actual["bytes"] != recorded["bytes"] or actual["sha256"] != recorded["sha256"]:
            raise OpsError("file_integrity_mismatch")
    return {"file_count": len(extracted), "total_bytes": sum(v["bytes"] for v in extracted.values())}


def publish_tree(staging: Path, target: Path) -> None:
    """Publish a verified tree into an empty/non-existent target only."""
    if target.exists():
        if not target.is_dir():
            raise OpsError("restore_target_not_directory")
        if any(target.iterdir()):
            raise OpsError("restore_target_not_empty")
        for child in sorted(staging.iterdir()):
            os.replace(child, target / child.name)
        staging.rmdir()
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging, target)


def restore_check(
    endpoint: str,
    machine: str,
    backup_id: str,
    token: str,
    target: Path,
) -> dict:
    if target.exists():
        if not target.is_dir():
            raise OpsError("restore_target_not_directory")
        if any(target.iterdir()):
            raise OpsError("restore_target_not_empty")
    status, manifest_raw = _http(
        "GET",
        _route_url(endpoint, machine, backup_id, CONTRACT.ARTIFACT_MANIFEST),
        token,
    )
    _expect(status, manifest_raw)
    try:
        manifest = CONTRACT.parse_manifest_bytes(manifest_raw, machine, backup_id)
    except CONTRACT.BackupError:
        raise OpsError("manifest_invalid")
    status, payload = _http(
        "GET",
        _route_url(endpoint, machine, backup_id, CONTRACT.ARTIFACT_PAYLOAD),
        token,
        max_response=CONTRACT.MAX_PAYLOAD_BYTES,
    )
    _expect(status, payload)
    try:
        CONTRACT.integrity_result(manifest, payload)
    except CONTRACT.BackupError:
        raise OpsError("integrity_mismatch")

    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name or 'restore'}.restore-", dir=str(target.parent))
    )
    payload_path = staging.parent / f".{staging.name}.payload.tar.gz"
    try:
        payload_path.write_bytes(payload)
        tree = extract_and_verify(payload_path, staging, manifest)
        publish_tree(staging, target)
    finally:
        if payload_path.exists():
            payload_path.unlink()
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return tree


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _command_inventory(args) -> int:
    roots = [Path(value) for value in args.root] if args.root else default_roots()
    inventory = build_inventory(roots)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(inventory, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
    else:
        _print_json(inventory)
    print(f"INVENTORY_OK roots={len(inventory['roots'])} files={inventory['file_count']} "
          f"bytes={inventory['total_bytes']} secret_paths={inventory['excluded']['secret_paths']} "
          f"secret_content={inventory['excluded']['secret_content']}")
    return 0


def _command_backup(args) -> int:
    roots = [Path(value) for value in args.root] if args.root else default_roots()
    backup_id = args.backup_id or default_backup_id()
    created_at = args.created_at or _utc_now()
    result = build_backup(roots, Path(args.out_dir), args.machine, backup_id, created_at)
    manifest = result["manifest"]
    print(f"BACKUP_DIR={Path(args.out_dir).resolve()}")
    print(f"BACKUP_ID={backup_id}")
    print(f"BACKUP_OK files={manifest['file_count']} bytes={manifest['total_bytes']} "
          f"payload_bytes={result['payload_bytes']} payload_sha256={result['payload_sha256']}")
    return 0


def _command_upload(args) -> int:
    directory = Path(args.dir)
    endpoint = _validate_endpoint(args.endpoint)
    if args.dry_run:
        try:
            manifest = CONTRACT.parse_manifest_bytes(
                (directory / "manifest.json").read_bytes(), args.machine, args.backup_id
            )
        except Exception:
            raise OpsError("manifest_missing")
        print(f"UPLOAD_PLAN machine={args.machine} backup_id={args.backup_id} "
              f"files={manifest['file_count']} payload_bytes={manifest['payload_bytes']} "
              f"payload_sha256={manifest['payload_sha256']}")
        print("NETWORK_MUTATION=NONE")
        return 0
    token = _token_from_env(args.token_env)
    result = upload_backup(endpoint, directory, args.machine, args.backup_id, token)
    print(f"UPLOAD_OK machine={args.machine} backup_id={args.backup_id} "
          f"files={result['file_count']} payload_bytes={result['payload_bytes']} "
          f"payload_sha256={result['payload_sha256']}")
    return 0


def _command_verify(args) -> int:
    token = _token_from_env(args.token_env)
    endpoint = _validate_endpoint(args.endpoint)
    result = verify_backup(
        endpoint,
        args.machine,
        args.backup_id,
        token,
        Path(args.dir) if args.dir else None,
    )
    print(f"VERIFY_OK machine={args.machine} backup_id={args.backup_id} "
          f"files={result['file_count']} bytes={result['bytes']} sha256={result['sha256']}")
    return 0


def _command_restore_check(args) -> int:
    token = _token_from_env(args.token_env)
    endpoint = _validate_endpoint(args.endpoint)
    result = restore_check(
        endpoint, args.machine, args.backup_id, token, Path(args.target)
    )
    print(f"RESTORE_CHECK_OK machine={args.machine} backup_id={args.backup_id} "
          f"files={result['file_count']} bytes={result['total_bytes']}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="read-only metadata inventory")
    inventory.add_argument("--root", action="append", default=[], help="root to inspect (repeatable)")
    inventory.add_argument("--json-out", default="", help="write the JSON inventory to this path")
    inventory.set_defaults(handler=_command_inventory)

    backup = subparsers.add_parser("backup", help="build payload.tar.gz and manifest.json")
    backup.add_argument("--root", action="append", default=[], help="root to back up (repeatable)")
    backup.add_argument("--out-dir", required=True, help="destination directory for the backup files")
    backup.add_argument("--machine", default="com2")
    backup.add_argument("--backup-id", default="")
    backup.add_argument("--created-at", default="", help="RFC3339 instant (for reproducible tests)")
    backup.set_defaults(handler=_command_backup)

    upload = subparsers.add_parser("upload", help="upload payload, manifest and verify")
    upload.add_argument("--endpoint", required=True)
    upload.add_argument("--dir", required=True)
    upload.add_argument("--machine", default="com2")
    upload.add_argument("--backup-id", required=True)
    upload.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    upload.add_argument("--dry-run", action="store_true")
    upload.set_defaults(handler=_command_upload)

    verify = subparsers.add_parser("verify", help="compare remote payload with its manifest")
    verify.add_argument("--endpoint", required=True)
    verify.add_argument("--machine", default="com2")
    verify.add_argument("--backup-id", required=True)
    verify.add_argument("--dir", default="")
    verify.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    verify.set_defaults(handler=_command_verify)

    restore = subparsers.add_parser("restore-check", help="download, verify and extract into an empty target")
    restore.add_argument("--endpoint", required=True)
    restore.add_argument("--machine", default="com2")
    restore.add_argument("--backup-id", required=True)
    restore.add_argument("--target", required=True)
    restore.add_argument("--token-env", default=DEFAULT_TOKEN_ENV)
    restore.set_defaults(handler=_command_restore_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command = args.command
    prefix = command.upper().replace("-", "_")
    try:
        return args.handler(args)
    except OpsError as exc:
        print(f"{prefix}_FAIL code={exc.code}", file=sys.stderr)
        return 1
    except CONTRACT.BackupError as exc:
        print(f"{prefix}_FAIL code={exc.code}", file=sys.stderr)
        return 1
    except Exception:
        # Never echo a path, file content or exception text; a bounded code only.
        print(f"{prefix}_FAIL code=unexpected_error", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
