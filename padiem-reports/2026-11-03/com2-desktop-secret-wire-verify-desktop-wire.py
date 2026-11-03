#!/usr/bin/env python3
"""Verify the COM2 desktop-secret wire on the live host (read-only checks).

Prints only booleans, lengths, last-four characters, tool ids and status codes.
Never prints a secret value, cookie or token.
"""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request

CHAT_UNIT = "padiem-chat-com2"
P01_UNIT = "padiem-p01"
SECRET_NAME = "CLAW_ENGINE_DESKTOP_SECRET"
CHAT_ORIGIN_NAME = "PADIEM_ENGINE_LOCAL_CHAT_ORIGIN"
P01_APP = "/opt/padiem/p01/app"


def main_pid(unit):
    return int(os.popen("systemctl show -p MainPID --value " + unit).read().strip())


def proc_env(pid):
    with open("/proc/" + str(pid) + "/environ", "rb") as handle:
        raw = handle.read()
    env = {}
    for item in raw.split(b"\0"):
        if not item:
            continue
        name, _, value = item.partition(b"=")
        env[name.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return env


chat_secret = proc_env(main_pid(CHAT_UNIT)).get(SECRET_NAME, "")
p01_environment = proc_env(main_pid(P01_UNIT))
p01_secret = p01_environment.get(SECRET_NAME, "")
p01_origin = p01_environment.get(CHAT_ORIGIN_NAME, "")

print("CHAT_SECRET_PRESENT=" + str(bool(chat_secret)))
print("P01_SECRET_PRESENT=" + str(bool(p01_secret)))
print("SECRET_LEN=" + str(len(p01_secret)) + " CHAT_LEN=" + str(len(chat_secret)))
print("SECRET_LAST4_MATCH=" + str(bool(chat_secret) and chat_secret[-4:] == p01_secret[-4:]))
print("SECRET_SAME=" + str(chat_secret == p01_secret and bool(chat_secret)))
print("P01_CHAT_ORIGIN_VALUE=" + p01_origin)
if not (chat_secret and p01_secret and chat_secret == p01_secret
        and p01_origin == "http://127.0.0.1:8798"):
    print("RESULT=ENV_INCOMPLETE")
    sys.exit(1)

os.chdir(P01_APP)
sys.path.insert(0, P01_APP)
from app.local_runtime import _env_view, install_worker_shims  # noqa: E402

install_worker_shims()
import worker_identity as identity  # noqa: E402

services = asyncio.run(identity._engine_services_for_env(_env_view(p01_environment)))
orchestration = services.orchestration
print("DESKTOP_DRIVER_REGISTERED=" + str(orchestration._desktop_step_driver_factory is not None))
print("PC_QUERY_DRIVER_REGISTERED=" + str(orchestration._pc_query_step_driver_factory is not None))
resolver = orchestration._tool_binding_resolver
if resolver is None:
    print("RESULT=NO_RESOLVER")
    sys.exit(1)
claw = resolver("b54-padiem-claw")
chat = resolver("padiem-chat")
print("CLAW_TOOL_IDS=" + ",".join(
    sorted(entry.runtime_tool_id for entry in claw.registry.entries) if claw else "NONE"
))
print("CHAT_TOOL_IDS=" + ",".join(
    sorted(entry.runtime_tool_id for entry in chat.registry.entries) if chat else "NONE"
))

body = json.dumps(
    {"subject_id": "verify-261103", "run_id": "run-verify-261103", "mode": "run_status"},
    separators=(",", ":"),
).encode()
timestamp = str(int(time.time()))
proof = hmac.new(chat_secret.encode(), timestamp.encode("ascii") + b"." + body,
                 hashlib.sha256).hexdigest()

# Chat's ingress is behind the COM2 edge guard: every non-GET /health request
# needs the four edge proof headers. Mint them exactly like the edge would,
# from the host's own edge secret file, so this probe reaches the desktop
# route instead of stopping at the guard. The secret is never printed.
chat_environment = proc_env(main_pid(CHAT_UNIT))
edge_path = chat_environment.get("PADIEM_COM2_EDGE_SECRET_FILE", "").strip()
if not edge_path:
    print("EDGE_SECRET_FILE_MISSING=1")
    sys.exit(1)
with open(edge_path, encoding="utf-8") as handle:
    edge_key = handle.read().strip().encode("utf-8")
edge_at = str(int(time.time()))
edge_id = os.urandom(32).hex()
edge_tls = "TLSv1.3"
signed = "\n".join(("v1", "POST", "/internal/claw/engine-desktop", edge_at, edge_id, edge_tls)).encode()
edge_proof = "v1=" + hmac.new(edge_key, signed, hashlib.sha256).hexdigest()

request = urllib.request.Request(
    "http://127.0.0.1:8798/internal/claw/engine-desktop",
    data=body,
    method="POST",
    headers={
        "Content-Type": "application/json",
        "X-Claw-Engine-Time": timestamp,
        "X-Claw-Engine-Proof": proof,
        "X-Padiem-Edge-At": edge_at,
        "X-Padiem-Edge-Id": edge_id,
        "X-Padiem-Edge-Tls": edge_tls,
        "X-Padiem-Edge-Proof": edge_proof,
    },
)
status, code = None, None
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        status, code = response.status, "ok"
except urllib.error.HTTPError as error:
    status = error.code
    try:
        code = json.loads(error.read().decode("utf-8", "replace")).get("error", {}).get("code")
    except Exception:
        code = "unparsed"
print("SIGNED_CALL_STATUS=" + str(status) + " CODE=" + str(code))
print("NOT_UNCONFIGURED_503=" + str(not (status == 503 and code == "claw_engine_desktop_unconfigured")))
