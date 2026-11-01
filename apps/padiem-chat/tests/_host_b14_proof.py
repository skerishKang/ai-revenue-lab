"""Shared synthetic B14 proof boundary for the host round-trip tests."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

TEST_SECRET = "synthetic-host-proof-" + "q" * 40
_path = Path(__file__).resolve().parents[2] / "korean-ai-platform/app/pilot/service_proof.py"
_spec = importlib.util.spec_from_file_location("_host_roundtrip_b14_proof", _path)
assert _spec and _spec.loader
_proof = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _proof
_spec.loader.exec_module(_proof)


def valid_proof(scope, body: bytes) -> bool:
    headers = dict(scope.get("headers", []))
    return _proof.verify_service_proof(
        TEST_SECRET,
        headers.get(b"x-padiem-b14-time", b"").decode("ascii", errors="ignore"),
        headers.get(b"x-padiem-b14-proof", b"").decode("ascii", errors="ignore"),
        body,
    )


async def reject_invalid_proof(scope, body: bytes, send) -> bool:
    if valid_proof(scope, body):
        return False
    await send({"type": "http.response.start", "status": 401, "headers": []})
    await send({"type": "http.response.body", "body": b"invalid service proof"})
    return True
