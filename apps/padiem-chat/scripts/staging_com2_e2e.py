"""Loopback-only staging Chat contract checks. Requires an isolated mock runtime."""
import argparse
import json
import os
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def run(base, cookie):
    u = urlsplit(base)
    if (u.scheme != "http" or u.hostname not in ("127.0.0.1", "::1", "localhost")
            or u.username or u.password or u.path not in ("", "/") or u.query or u.fragment):
        raise ValueError("Only an HTTP loopback origin is allowed")
    base = base.rstrip("/")
    if not cookie or "\n" in cookie or "\r" in cookie:
        raise ValueError("STAGING_CHAT_COOKIE must contain a session cookie header")
    opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(method, path, body=None, signed=True):
        headers = {"Accept": "application/json"}
        if signed:
            headers["Cookie"] = cookie
        if body is not None:
            headers["Content-Type"] = "application/json"
            headers["Origin"] = base
        req = Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                      headers=headers, method=method)
        try:
            response = opener.open(req, timeout=30)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read())

    status, health = request("GET", "/health", signed=False)
    assert status == 200 and health.get("status") == "ok" and health.get("app") == "padiem-chat"
    # Fail closed before any write if the server is not an isolated mock runtime.
    assert health.get("runtime") == "mock", "mock runtime required"
    print("PASS health")
    status, guest = request("GET", "/api/auth/status", signed=False)
    assert status == 200 and guest.get("authenticated") is False and guest.get("user") is None
    print("PASS auth guest")
    status, auth = request("GET", "/api/auth/status")
    assert status == 200 and auth.get("ready") is True and auth.get("authenticated") is True
    assert isinstance(auth.get("user"), dict) and auth.get("history_ready") is True
    print("PASS auth signed in")
    status, chat = request("POST", "/api/chat", {"messages": [{"role": "user", "content": "staging e2e probe"}]})
    assert status == 200 and isinstance(chat.get("answer"), str) and chat["answer"]
    cid = chat.get("conversation_id")
    assert isinstance(cid, str) and cid.startswith("chat_")
    print("PASS first chat turn and creation")
    status, conversations = request("GET", "/api/conversations")
    assert status == 200 and isinstance(conversations.get("conversations"), list)
    assert any(item.get("id") == cid for item in conversations["conversations"])
    print("PASS conversation list")
    status, files = request("GET", "/api/project-files")
    if auth.get("project_files_ready") is True:
        assert status == 200 and isinstance(files.get("files"), list)
        assert isinstance(files.get("has_more"), bool) and "next_cursor" in files
        print("PASS project files ready")
    else:
        assert status == 503 and files.get("error", {}).get("code") == "project_files_unavailable"
        print("PASS project files unavailable")
    status, caps = request("GET", "/api/files/capabilities")
    assert status == 200 and isinstance(caps.get("ready"), bool)
    assert isinstance(caps.get("auto_bytes"), int) and isinstance(caps.get("formats"), list)
    print("PASS attachment capabilities", "ready" if caps["ready"] else "unavailable")
    status, pc = request("GET", "/api/claw/local-access/devices")
    assert status == 200 and isinstance(pc.get("available"), bool)
    if pc["available"]:
        assert pc.get("ok") is True and isinstance(pc.get("devices"), list)
        print("PASS PC cards ready")
    else:
        assert "devices" not in pc
        print("PASS PC cards unavailable")
    return 8


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="isolated mock Chat loopback origin")
    args = parser.parse_args()
    try:
        count = run(args.base_url, os.environ.get("STAGING_CHAT_COOKIE", ""))
    except Exception as exc:
        # Never include URLs, response bodies, cookies or exception messages.
        print("FAIL", type(exc).__name__)
        return 1
    print("PASS", count, "checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
