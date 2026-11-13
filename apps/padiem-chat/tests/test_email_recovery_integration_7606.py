"""Real auth registry + real signed Chat routes/SQLite, with a fake mailbox."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

from app.password_auth import verify_password
from test_email_recovery_7606 import BASE, EMAIL, EPOCH, PASSWORD, build


@pytest.mark.parametrize("scenario", ["normal", "rollback", "response_lost"])
def test_real_auth_and_migrated_chat_restore_same_account_across_failures(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node with node:sqlite is required for cross-runtime integration")
    app, db, mail = build()
    if scenario == "rollback":
        db.connection.execute("CREATE TRIGGER fail_recovery BEFORE INSERT ON password_credentials "
                              "BEGIN SELECT RAISE(ABORT, 'synthetic_store_failure'); END")

    class Bridge(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def answer(self, status, body):
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/__test__/mailbox":
                payload = {"token": mail.token()}
            elif self.path == "/__test__/state":
                user_row = db.connection.execute("SELECT id FROM users LIMIT 1").fetchone()
                payload = {"users": db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                           "user_id": user_row[0] if user_row else None,
                           "credentials": db.connection.execute("SELECT COUNT(*) FROM password_credentials").fetchone()[0],
                           "consumed": db.connection.execute("SELECT COUNT(*) FROM password_recovery_tokens WHERE consumed_at IS NOT NULL").fetchone()[0]}
            else:
                self.answer(404, b"{}"); return
            self.answer(200, json.dumps(payload).encode())

        def do_POST(self):
            if self.path == "/__test__/allow-store":
                db.connection.execute("DROP TRIGGER fail_recovery")
                self.answer(200, b"{}"); return
            body = self.rfile.read(int(self.headers.get("content-length", "0")))

            async def call():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
                    return await client.post(self.path, content=body, headers=dict(self.headers))

            result = asyncio.run(call())
            self.answer(result.status_code, result.content)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Bridge)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [node, str(Path(__file__).parent / "fixtures/email_recovery_auth_bridge_7606.mjs"),
             str(server.server_port), scenario], capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["same_account"] and report["no_new_account"] and report["sessions_revoked"]
        assert len(mail.messages) == 1
        credential = db.connection.execute("SELECT password_hash,created_at FROM password_credentials").fetchone()
        assert verify_password(PASSWORD, credential["password_hash"])
        assert not verify_password("old-password-does-not-matter", credential["password_hash"])
        assert credential["created_at"] == EPOCH
        assert db.connection.execute("SELECT email FROM users").fetchone()[0] == EMAIL
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
