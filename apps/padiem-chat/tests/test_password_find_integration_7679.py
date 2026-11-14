"""Password find (#7679): real auth registry + real signed Chat routes/SQLite."""
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

from app.auth_validation_cache import SqliteAuthValidationCache
from app.history import D1HistoryStore
from app.password_auth import hash_password, verify_password
from test_email_recovery_7606 import BASE, EMAIL, PASSWORD, build

OLD_PASSWORD = "existing-password-7679"


@pytest.mark.parametrize("scenario", ["normal", "chat_sessions_stuck"])
def test_real_auth_and_migrated_chat_change_the_password_of_the_same_account(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node with node:sqlite is required for cross-runtime integration")
    app, db, mail = build()
    object.__setattr__(app.state.settings, "password_find_enabled", True)
    store = D1HistoryStore(db)
    asyncio.run(store.register_password_user(EMAIL, EMAIL, "User", hash_password(OLD_PASSWORD)))
    before = asyncio.run(store.find_password_credential(EMAIL))
    if scenario == "chat_sessions_stuck":
        # Local verification on with no revocation store: Chat must fail closed.
        object.__setattr__(app.state.settings, "local_verify_enabled", True)

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
                payload = {"token": mail.token(), "count": len(mail.messages)}
            elif self.path == "/__test__/state":
                row = db.connection.execute(
                    "SELECT user_id,password_hash,created_at FROM password_credentials").fetchone()
                payload = {"users": db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0],
                           "user_id": row["user_id"], "created_at": row["created_at"],
                           "changed": verify_password(PASSWORD, row["password_hash"]),
                           "tokens": db.connection.execute("SELECT COUNT(*) FROM password_recovery_tokens").fetchone()[0]}
            else:
                self.answer(404, b"{}"); return
            self.answer(200, json.dumps(payload).encode())

        def do_POST(self):
            if self.path == "/__test__/allow-sessions":
                app.state.auth_validation_cache = SqliteAuthValidationCache(db)
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
            [node, str(Path(__file__).parent / "fixtures/password_find_auth_bridge_7679.mjs"),
             str(server.server_port), scenario], capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report["same_account"] and report["sessions_revoked"]
        assert report["first_status"] == (503 if scenario == "chat_sessions_stuck" else None)
        assert len(mail.messages) == 1
        after = asyncio.run(store.find_password_credential(EMAIL))
        assert verify_password(PASSWORD, after.password_hash)
        assert not verify_password(OLD_PASSWORD, after.password_hash)
        assert (after.user.id, after.created_at) == (before.user.id, before.created_at)
        assert db.connection.execute("SELECT COUNT(*) FROM password_recovery_tokens").fetchone()[0] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
