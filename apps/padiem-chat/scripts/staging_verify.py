"""Check staging metadata without printing binding values or credentials."""
import json
import re
import sys
from pathlib import Path

DB = "e064ac35-6e45-4fd8-9a2c-c3ae6583c964"
DB_NAME = "padiem-chat-staging-db"

def verify_d1(data):
    items = data if isinstance(data, list) else data.get("result", [])
    if len([d for d in items if d.get("name") == DB_NAME and d.get("uuid") == DB]) != 1:
        raise ValueError("staging D1 identity mismatch")

def active_version(data):
    if not isinstance(data, list) or not data:
        raise ValueError("no deployments")
    versions = data[-1].get("versions", [])
    if len(versions) != 1 or versions[0].get("percentage") != 100:
        raise ValueError("ambiguous staging traffic")
    value = versions[0].get("version_id", "")
    if not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
        raise ValueError("invalid version")
    return value

def verify_bindings(data):
    bindings = data.get("resources", {}).get("bindings", [])
    dbs = [b for b in bindings if b.get("type") == "d1"]
    if len(dbs) != 1 or dbs[0].get("name") != "PADIEM_CHAT_DB" or (dbs[0].get("id") or dbs[0].get("database_id")) != DB:
        raise ValueError("staging D1 binding mismatch")
    allowed = {("assets", "ASSETS"), ("version_metadata", "CF_VERSION_METADATA"),
               ("d1", "PADIEM_CHAT_DB")}
    allowed.update(("plain_text", name) for name in ["PADIEM_CHAT_LIVE_ENABLED", "PADIEM_CHAT_PUBLIC_BASE_URL",
                   "PADIEM_CHAT_RUNTIME_MODE", "PADIEM_CHAT_SHARED_AUTH_COMPARE_ENABLED", "PADIEM_CHAT_SHARED_LOGIN_ENABLED",
                   "PC_QUEUE_BACKEND", "PC_QUEUE_ORIGIN"])
    if any((b.get("type"), b.get("name")) not in allowed for b in bindings):
        raise ValueError("unexpected binding")
    names = {b.get("name") for b in bindings}
    if not {"ASSETS", "CF_VERSION_METADATA", "PC_QUEUE_BACKEND"}.issubset(names):
        raise ValueError("missing staging binding")
    expected = {"PC_QUEUE_BACKEND": "d1", "PC_QUEUE_ORIGIN": "https://queue-staging.padiem.net",
                "PADIEM_CHAT_SHARED_LOGIN_ENABLED": "false", "PADIEM_CHAT_SHARED_AUTH_COMPARE_ENABLED": "false",
                "PADIEM_CHAT_RUNTIME_MODE": "mock", "PADIEM_CHAT_LIVE_ENABLED": "false",
                "PADIEM_CHAT_PUBLIC_BASE_URL": "https://padiem-chat-staging.charliekant.workers.dev"}
    for name, value in expected.items():
        if len([b for b in bindings if b.get("name") == name and b.get("type") == "plain_text" and b.get("text") == value]) != 1:
            raise ValueError("unexpected staging runtime setting")

if __name__ == "__main__":
    try:
        action, path = sys.argv[1:]
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if action == "d1": verify_d1(data)
        elif action == "active": print(active_version(data))
        elif action == "bindings": verify_bindings(data)
        else: raise ValueError("unknown verification")
    except (ValueError, KeyError, TypeError, OSError):
        raise SystemExit("Staging metadata verification failed") from None
