"""Private D1 GitHub App user-to-server OAuth store. Never persists plaintext tokens."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
import time
from typing import Any
from padiem_control_plane.cloudflare_aes_gcm import CloudflareAesGcmPort

def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def _row(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_py"):
        candidate = value.to_py()
        return candidate if isinstance(candidate, dict) else None
    return dict(value) if hasattr(value, "items") else None

class D1GitHubOAuthStore:
    def __init__(self, db: Any, *, session_secret: str, cipher: Any | None = None):
        if db is None or not session_secret or len(session_secret) < 32:
            raise ValueError("Trusted D1 and strong product session secret required")
        self.db = db
        # Purpose-separated AES key, derived from the pre-existing server-only product secret.
        self.key = hmac.digest(session_secret.encode(), b"padiem-claw-github-token-aes-gcm-v1", "sha256")
        self.cipher = cipher if cipher is not None else CloudflareAesGcmPort()

    async def _first(self, sql: str, *values: Any) -> dict[str, Any] | None:
        return _row(await self.db.prepare(sql).bind(*values).first())

    async def _run(self, sql: str, *values: Any) -> Any:
        return await self.db.prepare(sql).bind(*values).run()

    async def begin(self, *, user_id: str, session: str, state: str, verifier: str, now: int | None = None):
        t = int(time.time() if now is None else now)
        if not all(isinstance(x, str) and x for x in (user_id, session, state, verifier)):
            raise ValueError("missing canonical owner/session and PKCE authority")
        await self._run(
            "INSERT INTO claw_github_oauth_states(state_sha256,user_id,session_sha256,pkce_verifier,expires_at,created_at) VALUES(?,?,?,?,?,?)",
            _digest(state), user_id, _digest(session), verifier, t + 600, t,
        )

    async def consume(self, *, user_id: str, session: str, state: str, now: int | None = None) -> str | None:
        t = int(time.time() if now is None else now)
        record = await self._first(
            "DELETE FROM claw_github_oauth_states WHERE state_sha256=? AND user_id=? AND session_sha256=? AND expires_at>? RETURNING pkce_verifier",
            _digest(state), user_id, _digest(session), t,
        )
        return record.get("pkce_verifier") if record else None

    async def save(self, *, user_id: str, github_user_id: int, login: str, installation_id: int,
                   access_token: str, refresh_token: str, access_expires_at: int, refresh_expires_at: int):
        if not (user_id and isinstance(github_user_id, int) and github_user_id > 0 and
                isinstance(installation_id, int) and installation_id > 0 and
                isinstance(login, str) and login and access_token and refresh_token and
                isinstance(refresh_expires_at, int) and refresh_expires_at > int(time.time())):
            raise ValueError("GitHub verified binding required")
        iv = self.cipher.random_bytes(12)
        plaintext = json.dumps({"access_token": access_token, "refresh_token": refresh_token}, separators=(",", ":")).encode()
        ciphertext = await self.cipher.encrypt(key=self.key, iv=iv, plaintext=plaintext,
                                               additional_data=("padiem-gh:"+user_id).encode())
        sealed = base64.b64encode(iv + ciphertext).decode("ascii")
        t = int(time.time())
        await self._run(
            """INSERT INTO claw_github_connections
                (user_id,github_user_id,github_login,installation_id,sealed_credential,access_expires_at,refresh_expires_at,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(user_id) DO UPDATE SET
                github_user_id=excluded.github_user_id,github_login=excluded.github_login,
                installation_id=excluded.installation_id,sealed_credential=excluded.sealed_credential,
                enabled=1,
                access_expires_at=excluded.access_expires_at,
                refresh_expires_at=excluded.refresh_expires_at,updated_at=excluded.updated_at""",
            user_id, github_user_id, login, installation_id, sealed, access_expires_at, refresh_expires_at, t, t,
        )

    async def status(self, user_id: str):
        row = await self._first(
            "SELECT github_login,installation_id,refresh_expires_at,enabled FROM claw_github_connections WHERE user_id=?",
            user_id,
        )
        if not row:
            return None
        if int(row["refresh_expires_at"]) <= int(time.time()):
            return None
        return {"login": row["github_login"], "installation_id": int(row["installation_id"]),
                "enabled": int(row["enabled"]) == 1}

    async def token_pair(self, user_id: str) -> dict[str, Any] | None:
        row = await self._first(
            "SELECT sealed_credential,access_expires_at,refresh_expires_at FROM claw_github_connections WHERE user_id=?", user_id,
        )
        if not row or int(row["refresh_expires_at"]) <= int(time.time()):
            return None
        try:
            data = base64.b64decode(row["sealed_credential"], validate=True)
            plaintext = await self.cipher.decrypt(key=self.key, iv=data[:12],
                      ciphertext=data[12:], additional_data=("padiem-gh:"+user_id).encode())
            value = json.loads(plaintext.decode("utf-8"))
            if not isinstance(value.get("access_token"), str) or not isinstance(value.get("refresh_token"), str):
                return None
            return {**value, "access_expires_at": int(row["access_expires_at"]),
                    "refresh_expires_at": int(row["refresh_expires_at"])}
        except Exception:
            return None

    async def set_enabled(self, user_id: str, enabled: bool):
        await self._run("UPDATE claw_github_connections SET enabled=?,updated_at=? WHERE user_id=?",
                        1 if enabled else 0, int(time.time()), user_id)

    async def disconnect(self, user_id: str):
        await self._run("DELETE FROM claw_github_connections WHERE user_id=?", user_id)
