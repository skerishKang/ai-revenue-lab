from __future__ import annotations

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
