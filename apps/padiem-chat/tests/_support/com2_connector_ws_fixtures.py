"""#8061: shared COM2 gateway WebSocket test fixtures.

Moved verbatim from ``test_com2_connector_websocket.py`` so sibling test modules
stop importing a test file. Values, methods and assertions are unchanged.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timedelta, timezone

from app.canonical_connector_gateway_source_composition import CONNECTOR_GATEWAY_WSS_PATH as PATH

SECRET = "synthetic-" + "s" * 32
CHALLENGE = "pairing." + "a" * 32
DEVICE = "device.test"
LEASE = "gateway.test"


class Identity:
    async def resolve_connector_enrollment_consent_for_device(self, payload):
        raise AssertionError("not yet authorized")
    async def bind_connector_enrollment_challenge(self, payload):
        raise AssertionError("not yet authorized")
    async def authorize_connector_enrollment_redeem(self, payload):
        raise AssertionError("not yet authorized")


class Broker:
    def __init__(self):
        self.calls = []
    async def gateway_bootstrap_rpc(self, payload):
        self.calls.append(payload["operation"])
        common = {"challenge_id": CHALLENGE, "device_id": DEVICE, "lease_ref": LEASE}
        if payload["operation"] == "begin":
            common.update(nonce_hex="c" * 64, expires_at=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat(), credential=False, challenge_consumed=False)
        elif payload["operation"] == "finish":
            common.update(verified=True, credential=False, challenge_consumed=False)
        elif payload["operation"] == "authorize":
            common.update(action=payload["args"]["action"], counter=payload["args"]["counter"], authenticated=True)
        else:
            return {"ok": False, "error": {"code": "disabled", "message": "disabled"}}
        return {"ok": True, "gateway": common}
    async def get_enrollment_binding(self, payload):
        return {"ok": False, "error": {"code": "test_refused", "message": "refused"}}
    async def verify_enrollment_bootstrap(self, payload): raise AssertionError()
    async def redeem_enrollment(self, payload): raise AssertionError()
    async def revoke_binding(self, payload): raise AssertionError()


def signed(request_id):
    at = str(int(time.time()))
    tls = "TLSv1.3"
    raw = "\n".join(("v1", "GET", PATH, at, request_id, tls)).encode()
    return {
        "x-padiem-edge-at": at, "x-padiem-edge-id": request_id,
        "x-padiem-edge-tls": tls,
        "x-padiem-edge-proof": "v1=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest(),
    }
