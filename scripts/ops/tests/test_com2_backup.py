from __future__ import annotations

import base64
import hashlib
import http.server
import importlib.util
import io
import json
import sys
import tarfile
import threading
import types
import urllib.parse
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "com2_backup.py"
TOKEN = "fixture-token-value"
BACKUP_ID = "20261019t120000z"
CREATED_AT = "2026-10-19T12:00:00Z"
ENC_KEY = hashlib.sha256(b"com2-backup-test-encryption-key").digest()
ENC_KEY_HEX = ENC_KEY.hex()
ENC_KEY_B64 = base64.urlsafe_b64encode(ENC_KEY).decode("ascii").rstrip("=")
OTHER_KEY = hashlib.sha256(b"com2-backup-test-other-key").digest()
ENC_KEY_ID = "com2-test-20261019"
KEY_ENV = "COM2_BACKUP_TEST_KEY"


def _load():
    spec = importlib.util.spec_from_file_location("com2_backup_ops", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


backup_ops = _load()


def _make_tree(root: Path) -> None:
    (root / "settings").mkdir()
    (root / "settings" / "app.json").write_text('{"mode":"offline"}', encoding="utf-8")
    (root / "settings" / "marked.json").write_text(
        '{"api_key":"inert-fixture-marker"}', encoding="utf-8"
    )
    (root / "state").mkdir()
    (root / "state" / "state.txt").write_bytes(b"state=ready\n")
    (root / "secrets").mkdir()
    (root / "secrets" / "token.txt").write_text("fixture-secret-value", encoding="utf-8")
    (root / ".env").write_text("API_KEY=fixture-secret-value", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")


def _build_backup(root: Path, out: Path) -> None:
    exit_code = backup_ops.main(
        [
            "backup",
            "--root",
            str(root),
            "--out-dir",
            str(out),
            "--machine",
            "com2",
            "--backup-id",
            BACKUP_ID,
            "--created-at",
            CREATED_AT,
        ]
    )
    assert exit_code == 0


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    token = TOKEN
    objects: dict[str, bytes] = {}

    def log_message(self, *_args):  # keep test output clean
        return None

    def _send(self, status: int, body: bytes, content_type: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str) -> None:
        self._send(status, json.dumps({"ok": False, "error": {"code": code}}).encode())

    def _authorized(self) -> bool:
        return self.headers.get("Authorization") == f"Bearer {self.token}"

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def do_PUT(self):
        if not self._authorized():
            return self._error(401, "backup_unauthorized")
        path = urllib.parse.urlsplit(self.path).path
        body = self._body()
        if path.endswith("/payload"):
            expected = self.headers.get("X-Padiem-Content-Sha256", "")
            if hashlib.sha256(body).hexdigest() != expected:
                return self._error(400, "checksum_mismatch")
        elif path.endswith("/manifest"):
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return self._error(415, "unsupported_media_type")
        else:
            return self._error(404, "not_found")
        if path in self.objects and self.objects[path] != body:
            return self._error(409, "backup_conflict_no_overwrite")
        self.objects[path] = body
        return self._send(200, json.dumps({"ok": True}).encode())

    def do_GET(self):
        if not self._authorized():
            return self._error(401, "backup_unauthorized")
        path = urllib.parse.urlsplit(self.path).path
        body = self.objects.get(path)
        if body is None:
            return self._error(404, "not_found")
        content_type = "application/gzip" if path.endswith("/payload") else "application/json"
        return self._send(200, body, content_type)

    def do_POST(self):
        if not self._authorized():
            return self._error(401, "backup_unauthorized")
        path = urllib.parse.urlsplit(self.path).path
        prefix = path[: -len("/verify")]
        from apps_contract import CONTRACT  # local alias set below

        manifest = CONTRACT.parse_manifest_bytes(
            self.objects.get(prefix + "/manifest", b""), "com2", BACKUP_ID
        )
        payload = self.objects.get(prefix + "/payload")
        if payload is None:
            return self._error(404, "payload_not_found")
        try:
            CONTRACT.integrity_result(manifest, payload)
        except CONTRACT.BackupError:
            return self._error(409, "integrity_mismatch")
        return self._send(200, json.dumps({"ok": True, "result": "verified"}).encode())


# The handler cannot import the script's dynamically loaded contract directly;
# expose it through a tiny module alias for the test process.
_contract_module = types.ModuleType("apps_contract")
_contract_module.CONTRACT = backup_ops.CONTRACT
sys.modules["apps_contract"] = _contract_module


@pytest.fixture
def server():
    handler = type("BackupHandler", (_Handler,), {})
    handler.objects = {}
    instance = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{instance.server_port}", handler
    finally:
        instance.shutdown()
        instance.server_close()
        thread.join(timeout=5)


def test_inventory_excludes_secret_paths_and_never_prints_values(tmp_path, capsys):
    root = tmp_path / "data"
    root.mkdir()
    _make_tree(root)

    exit_code = backup_ops.main(["inventory", "--root", str(root)])
    captured = capsys.readouterr()
    assert exit_code == 0

    inventory = json.loads(captured.out.splitlines()[0])
    paths = {entry["path"] for entry in inventory["files"]}
    assert "root-1/settings/app.json" in paths
    assert "root-1/state/state.txt" in paths
    assert not any("secrets/" in path for path in paths)
    assert not any(path.endswith("/.env") for path in paths)
    assert not any(path.endswith("marked.json") for path in paths)
    assert "fixture-secret-value" not in captured.out
    # ``secrets/`` is pruned as a directory, so only ``.env`` is counted as a
    # secret-named file; its contents were never read or printed.
    assert inventory["excluded"]["secret_paths"] == 1
    assert inventory["excluded"]["secret_content"] == 1
    assert "INVENTORY_OK" in captured.out


def test_backup_is_deterministic_and_manifest_matches_archive(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    _make_tree(root)
    first = tmp_path / "first"
    second = tmp_path / "second"
    _build_backup(root, first)
    _build_backup(root, second)

    manifest_first = (first / "manifest.json").read_bytes()
    manifest_second = (second / "manifest.json").read_bytes()
    assert manifest_first == manifest_second
    assert (first / "payload.tar.gz").read_bytes() == (second / "payload.tar.gz").read_bytes()

    manifest = backup_ops.CONTRACT.parse_manifest_bytes(manifest_first, "com2", BACKUP_ID)
    assert manifest["file_count"] == 2
    assert {entry["path"] for entry in manifest["files"]} == {
        "root-1/settings/app.json",
        "root-1/state/state.txt",
    }
    with tarfile.open(first / "payload.tar.gz", "r:gz") as archive:
        assert archive.getnames() == [entry["path"] for entry in manifest["files"]]
        assert archive.extractfile("root-1/state/state.txt").read() == b"state=ready\n"


def test_loopback_upload_verify_and_restore_check(tmp_path, server, monkeypatch, capsys):
    endpoint, _handler = server
    monkeypatch.setenv("COM2_BACKUP_WRITE_TOKEN", TOKEN)
    root = tmp_path / "data"
    root.mkdir()
    _make_tree(root)
    out = tmp_path / "backup"
    _build_backup(root, out)

    assert (
        backup_ops.main(
            [
                "upload",
                "--endpoint",
                endpoint,
                "--dir",
                str(out),
                "--machine",
                "com2",
                "--backup-id",
                BACKUP_ID,
            ]
        )
        == 0
    )
    assert "UPLOAD_OK" in capsys.readouterr().out

    assert (
        backup_ops.main(
            [
                "verify",
                "--endpoint",
                endpoint,
                "--dir",
                str(out),
                "--machine",
                "com2",
                "--backup-id",
                BACKUP_ID,
            ]
        )
        == 0
    )
    assert "VERIFY_OK" in capsys.readouterr().out

    target = tmp_path / "restored"
    assert (
        backup_ops.main(
            [
                "restore-check",
                "--endpoint",
                endpoint,
                "--target",
                str(target),
                "--machine",
                "com2",
                "--backup-id",
                BACKUP_ID,
            ]
        )
        == 0
    )
    assert "RESTORE_CHECK_OK" in capsys.readouterr().out
    assert (target / "root-1" / "settings" / "app.json").read_text(encoding="utf-8") == '{"mode":"offline"}'
    assert (target / "root-1" / "state" / "state.txt").read_bytes() == b"state=ready\n"
    assert not (target / "root-1" / "secrets").exists()
    assert not (target / "root-1" / ".env").exists()
    assert not (target / "root-1" / "settings" / "marked.json").exists()


def test_verify_detects_remote_tampering_and_restore_leaves_no_target(
    tmp_path, server, monkeypatch, capsys
):
    endpoint, handler = server
    monkeypatch.setenv("COM2_BACKUP_WRITE_TOKEN", TOKEN)
    root = tmp_path / "data"
    root.mkdir()
    _make_tree(root)
    out = tmp_path / "backup"
    _build_backup(root, out)
    assert backup_ops.main(
        ["upload", "--endpoint", endpoint, "--dir", str(out), "--backup-id", BACKUP_ID]
    ) == 0
    capsys.readouterr()

    payload_path = f"/internal/v1/com2-backup/com2/{BACKUP_ID}/payload"
    handler.objects[payload_path] = handler.objects[payload_path] + b"tampered"

    assert backup_ops.main(
        ["verify", "--endpoint", endpoint, "--machine", "com2", "--backup-id", BACKUP_ID]
    ) == 1
    assert "VERIFY_FAIL code=integrity_mismatch" in capsys.readouterr().err

    target = tmp_path / "restored"
    assert backup_ops.main(
        [
            "restore-check",
            "--endpoint",
            endpoint,
            "--target",
            str(target),
            "--machine",
            "com2",
            "--backup-id",
            BACKUP_ID,
        ]
    ) == 1
    assert not target.exists()


def test_restore_check_refuses_a_non_empty_target(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("COM2_BACKUP_WRITE_TOKEN", TOKEN)
    target = tmp_path / "occupied"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    exit_code = backup_ops.main(
        [
            "restore-check",
            "--endpoint",
            "http://127.0.0.1:9",
            "--target",
            str(target),
            "--machine",
            "com2",
            "--backup-id",
            BACKUP_ID,
        ]
    )
    assert exit_code == 1
    assert "restore_target_not_empty" in capsys.readouterr().err
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"
    assert list(target.iterdir()) == [target / "keep.txt"]


def test_extract_rejects_path_traversal_without_writing_outside(tmp_path):
    payload = tmp_path / "payload.tar.gz"
    with tarfile.open(payload, "w:gz") as archive:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        archive.addfile(info, io.BytesIO(b"x"))

    staging = tmp_path / "staging"
    with pytest.raises(backup_ops.OpsError) as exc:
        backup_ops.extract_and_verify(payload, staging, {"files": []})
    assert exc.value.code == "unsafe_archive_member"
    assert not (tmp_path / "escape.txt").exists()


def test_upload_rejects_plain_http_outside_loopback(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("COM2_BACKUP_WRITE_TOKEN", TOKEN)
    root = tmp_path / "data"
    root.mkdir()
    _make_tree(root)
    out = tmp_path / "backup"
    _build_backup(root, out)

    exit_code = backup_ops.main(
        [
            "upload",
            "--endpoint",
            "http://example.com",
            "--dir",
            str(out),
            "--machine",
            "com2",
            "--backup-id",
            BACKUP_ID,
        ]
    )
    assert exit_code == 1
    assert "endpoint_requires_https" in capsys.readouterr().err


def test_upload_dry_run_needs_no_token(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("COM2_BACKUP_WRITE_TOKEN", raising=False)
    root = tmp_path / "data"
    root.mkdir()
    _make_tree(root)
    out = tmp_path / "backup"
    _build_backup(root, out)

    exit_code = backup_ops.main(
        [
            "upload",
            "--endpoint",
            "http://127.0.0.1:9",
            "--dir",
            str(out),
            "--machine",
            "com2",
            "--backup-id",
            BACKUP_ID,
            "--dry-run",
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "UPLOAD_PLAN" in captured.out
    assert "NETWORK_MUTATION=NONE" in captured.out


# ---------------------------------------------------------------------------
# Client-side encrypted payload
# ---------------------------------------------------------------------------


def _run_backup(root: Path, out: Path, extra: tuple[str, ...] = ()) -> int:
    return backup_ops.main(
        [
            "backup",
            "--root",
            str(root),
            "--out-dir",
            str(out),
            "--machine",
            "com2",
            "--backup-id",
            BACKUP_ID,
            "--created-at",
            CREATED_AT,
            *extra,
        ]
    )


def _upload(endpoint: str, out: Path) -> int:
    return backup_ops.main(
        ["upload", "--endpoint", endpoint, "--dir", str(out), "--backup-id", BACKUP_ID]
    )


def _build_and_upload_encrypted(tmp_path, server, monkeypatch, capsys):
    endpoint, handler = server
    monkeypatch.setenv("COM2_BACKUP_WRITE_TOKEN", TOKEN)
    monkeypatch.setenv(KEY_ENV, ENC_KEY_HEX)
    root = tmp_path / "data"
    root.mkdir()
    _make_tree(root)
    out = tmp_path / "backup"
    assert _run_backup(root, out, ("--key-env", KEY_ENV, "--key-id", ENC_KEY_ID)) == 0
    assert _upload(endpoint, out) == 0
    return root, out, endpoint, handler


def test_encrypted_backup_round_trip_keeps_integrity_and_plaintext_restore(
    tmp_path, server, monkeypatch, capsys
):
    root, out, endpoint, _handler = _build_and_upload_encrypted(
        tmp_path, server, monkeypatch, capsys
    )
    setup_output = capsys.readouterr().out
    assert f"BACKUP_ENCRYPTION=AES-256-GCM key_id={ENC_KEY_ID}" in setup_output
    assert "UPLOAD_OK" in setup_output

    payload = (out / "payload.tar.gz").read_bytes()
    assert payload.startswith(backup_ops.ENCRYPTION_MAGIC)
    assert b"state=ready" not in payload
    assert b"fixture-secret-value" not in payload
    assert ENC_KEY not in payload

    manifest_text = (out / "manifest.json").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["payload_sha256"] == hashlib.sha256(payload).hexdigest()
    assert manifest["payload_bytes"] == len(payload)
    assert "encryption" not in manifest
    assert ENC_KEY.hex() not in manifest_text
    assert ENC_KEY_B64 not in manifest_text

    assert backup_ops.main(
        [
            "verify",
            "--endpoint",
            endpoint,
            "--dir",
            str(out),
            "--machine",
            "com2",
            "--backup-id",
            BACKUP_ID,
            "--key-id",
            ENC_KEY_ID,
        ]
    ) == 0
    verify_output = capsys.readouterr().out
    assert f"key_id={ENC_KEY_ID}" in verify_output
    assert ENC_KEY.hex() not in verify_output
    assert ENC_KEY_B64 not in verify_output

    target = tmp_path / "restored"
    assert backup_ops.main(
        [
            "restore-check",
            "--endpoint",
            endpoint,
            "--target",
            str(target),
            "--machine",
            "com2",
            "--backup-id",
            BACKUP_ID,
            "--key-env",
            KEY_ENV,
            "--key-id",
            ENC_KEY_ID,
        ]
    ) == 0
    restore_output = capsys.readouterr().out
    assert f"encrypted=YES key_id={ENC_KEY_ID}" in restore_output
    assert ENC_KEY.hex() not in restore_output
    assert ENC_KEY_B64 not in restore_output
    assert (target / "root-1" / "settings" / "app.json").read_text(encoding="utf-8") == '{"mode":"offline"}'
    assert (target / "root-1" / "state" / "state.txt").read_bytes() == b"state=ready\n"
    assert not (target / "root-1" / "settings" / "marked.json").exists()
    assert not (target / "root-1" / "secrets").exists()


def test_encrypted_restore_without_a_key_writes_nothing(
    tmp_path, server, monkeypatch, capsys
):
    _root, _out, endpoint, _handler = _build_and_upload_encrypted(
        tmp_path, server, monkeypatch, capsys
    )
    target = tmp_path / "restored"

    exit_code = backup_ops.main(
        [
            "restore-check",
            "--endpoint",
            endpoint,
            "--target",
            str(target),
            "--machine",
            "com2",
            "--backup-id",
            BACKUP_ID,
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "code=encryption_key_missing" in captured.err
    assert not target.exists()


def test_encrypted_restore_with_the_wrong_key_writes_nothing(
    tmp_path, server, monkeypatch, capsys
):
    _root, _out, endpoint, _handler = _build_and_upload_encrypted(
        tmp_path, server, monkeypatch, capsys
    )
    monkeypatch.setenv(KEY_ENV, OTHER_KEY.hex())
    target = tmp_path / "restored"

    exit_code = backup_ops.main(
        [
            "restore-check",
            "--endpoint",
            endpoint,
            "--target",
            str(target),
            "--machine",
            "com2",
            "--backup-id",
            BACKUP_ID,
            "--key-env",
            KEY_ENV,
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "code=decryption_failed" in captured.err
    assert not target.exists()
    assert OTHER_KEY.hex() not in captured.out + captured.err


def test_encrypted_verify_and_restore_reject_a_different_key_id(
    tmp_path, server, monkeypatch, capsys
):
    _root, _out, endpoint, _handler = _build_and_upload_encrypted(
        tmp_path, server, monkeypatch, capsys
    )

    assert backup_ops.main(
        [
            "verify",
            "--endpoint",
            endpoint,
            "--machine",
            "com2",
            "--backup-id",
            BACKUP_ID,
            "--key-id",
            "another-key-id",
        ]
    ) == 1
    assert "code=encryption_key_id_mismatch" in capsys.readouterr().err

    target = tmp_path / "restored"
    assert backup_ops.main(
        [
            "restore-check",
            "--endpoint",
            endpoint,
            "--target",
            str(target),
            "--machine",
            "com2",
            "--backup-id",
            BACKUP_ID,
            "--key-env",
            KEY_ENV,
            "--key-id",
            "another-key-id",
        ]
    ) == 1
    assert "code=encryption_key_id_mismatch" in capsys.readouterr().err
    assert not target.exists()


def test_encrypted_payload_tampering_is_detected(tmp_path, server, monkeypatch, capsys):
    _root, out, endpoint, handler = _build_and_upload_encrypted(
        tmp_path, server, monkeypatch, capsys
    )
    payload_path = f"/internal/v1/com2-backup/com2/{BACKUP_ID}/payload"
    tampered = bytearray(handler.objects[payload_path])
    tampered[-1] ^= 0x01

    # The stored SHA-256 still covers the ciphertext, so transport tampering is
    # rejected before any decryption attempt.
    handler.objects[payload_path] = bytes(tampered)
    assert backup_ops.main(
        ["verify", "--endpoint", endpoint, "--machine", "com2", "--backup-id", BACKUP_ID]
    ) == 1
    assert "code=integrity_mismatch" in capsys.readouterr().err

    # A re-sealed payload with a known checksum but a broken GCM tag fails
    # authenticated decryption rather than extracting attacker bytes.
    envelope = (out / "payload.tar.gz").read_bytes()
    corrupted = envelope[:-1] + bytes([envelope[-1] ^ 0x01])
    with pytest.raises(backup_ops.OpsError) as exc:
        backup_ops.decrypt_payload(corrupted, ENC_KEY, "com2", BACKUP_ID)
    assert exc.value.code == "decryption_failed"


def test_encryption_key_parsing_accepts_hex_and_base64_and_rejects_bad_values():
    assert backup_ops.parse_encryption_key(ENC_KEY_HEX) == ENC_KEY
    assert backup_ops.parse_encryption_key(ENC_KEY_B64) == ENC_KEY
    assert backup_ops.parse_encryption_key(f"  {ENC_KEY_HEX}\n") == ENC_KEY

    with pytest.raises(backup_ops.OpsError) as exc:
        backup_ops.parse_encryption_key("")
    assert exc.value.code == "encryption_key_missing"
    for bad in ("not-a-key", "ab" * 16, "00" * 33, "!!" * 24):
        with pytest.raises(backup_ops.OpsError) as exc:
            backup_ops.parse_encryption_key(bad)
        assert exc.value.code == "encryption_key_invalid"

    assert backup_ops.validate_key_id(ENC_KEY_ID) == ENC_KEY_ID
    for bad_id in ("", "-leading", "has space", "a" * 65):
        with pytest.raises(backup_ops.OpsError) as exc:
            backup_ops.validate_key_id(bad_id)
        assert exc.value.code == "encryption_key_id_invalid"


def test_encrypted_backup_requires_both_key_env_and_key_id(tmp_path, monkeypatch, capsys):
    root = tmp_path / "data"
    root.mkdir()
    _make_tree(root)
    out = tmp_path / "backup"

    monkeypatch.setenv(KEY_ENV, ENC_KEY_HEX)
    assert _run_backup(root, out, ("--key-env", KEY_ENV)) == 1
    assert "code=encryption_key_id_missing" in capsys.readouterr().err

    monkeypatch.delenv(KEY_ENV)
    assert _run_backup(root, out, ("--key-env", KEY_ENV, "--key-id", ENC_KEY_ID)) == 1
    captured = capsys.readouterr()
    assert "code=encryption_key_env_missing" in captured.err
    assert ENC_KEY_HEX not in captured.err

    assert _run_backup(root, out, ("--key-id", ENC_KEY_ID)) == 1
    assert "code=encryption_key_env_missing" in capsys.readouterr().err
    assert not (out / "payload.tar.gz").exists()
