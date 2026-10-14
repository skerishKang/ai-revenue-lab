"""GitHub App user-to-server OAuth provider: fixed GitHub hosts only, no browser tokens."""
from __future__ import annotations
import httpx

GITHUB_APP_ID = 5321929
GITHUB_CLIENT_ID = "Iv23liKN7UFDSli3stvg"

class GitHubAppOAuthProvider:
    def __init__(self, *, client_secret: str, transport=None):
        if not isinstance(client_secret, str) or not client_secret:
            raise ValueError("Private GitHub App client secret is required")
        self.client_secret = client_secret
        self.transport = transport

    async def _call(self, method: str, url: str, *, token: str | None = None, params=None):
        headers = {"Accept": ("application/json" if url.startswith("https://github.com/login/oauth/")
                               else "application/vnd.github+json"),
                   "User-Agent": "PADIEM-Claw-GitHub-App", "X-GitHub-Api-Version": "2026-03-10"}
        if token:
            headers["Authorization"] = "Bearer " + token
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as client:
            response = await client.request(method, url, headers=headers, data=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise RuntimeError("GitHub OAuth result malformed")
            return data

    async def exchange(self, *, code: str, verifier: str, callback_url: str):
        result = await self._call("POST", "https://github.com/login/oauth/access_token",
                                  params={"client_id": GITHUB_CLIENT_ID, "client_secret": self.client_secret,
                                          "code": code, "redirect_uri": callback_url, "code_verifier": verifier})
        return self._tokens(result)

    async def refresh(self, *, refresh_token: str):
        result = await self._call("POST", "https://github.com/login/oauth/access_token",
            params={"client_id": GITHUB_CLIENT_ID, "client_secret": self.client_secret,
                    "refresh_token": refresh_token, "grant_type": "refresh_token"})
        return self._tokens(result)

    @staticmethod
    def _tokens(data):
        import time
        access = data.get("access_token")
        refresh = data.get("refresh_token")
        if not isinstance(access, str) or not access.startswith("ghu_") or not isinstance(refresh, str) or not refresh.startswith("ghr_"):
            raise ValueError("GitHub OAuth token exchange declined")
        expires = data.get("expires_in")
        refresh_expires = data.get("refresh_token_expires_in")
        if not isinstance(expires, int) or not 1 <= expires <= 86400 or not isinstance(refresh_expires, int) or not 1 <= refresh_expires <= 20000000:
            raise ValueError("GitHub OAuth expiry malformed")
        now = int(time.time())
        return {"access_token": access, "refresh_token": refresh,
                "access_expires_at": now + expires, "refresh_expires_at": now + refresh_expires}

    async def viewer(self, token: str):
        data = await self._call("GET", "https://api.github.com/user", token=token)
        identity, login = data.get("id"), data.get("login")
        if not isinstance(identity, int) or identity < 1 or not isinstance(login, str) or not login:
            raise ValueError("GitHub user identity not verified")
        return identity, login

    async def installation(self, token: str):
        data = await self._call("GET", "https://api.github.com/user/installations", token=token)
        items = data.get("installations")
        if not isinstance(items, list):
            raise ValueError("GitHub installation authority unavailable")
        valid = [entry.get("id") for entry in items
                 if isinstance(entry, dict) and entry.get("app_id") == GITHUB_APP_ID
                 and isinstance(entry.get("id"), int) and entry["id"] > 0]
        # Do not silently choose another organization/tenant if more than one installation exists.
        if len(valid) != 1:
            raise ValueError("GitHub installation missing or ambiguous")
        return valid[0]

    async def repositories(self, token: str, installation_id: int):
        data = await self._call("GET",
            f"https://api.github.com/user/installations/{installation_id}/repositories", token=token)
        entries = data.get("repositories")
        if not isinstance(entries, list):
            raise ValueError("GitHub repositories unavailable")
        return [{"full_name": item["full_name"], "private": item.get("private") is True}
                for item in entries[:50] if isinstance(item, dict)
                and isinstance(item.get("full_name"), str)]
