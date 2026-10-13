"""Test-only REAL Python->Python Cloudflare Worker Service Binding caller.

Never import this from public B62 or ship it to the network. This is one
isolated local CI process with two mock private binding targets, both default
DENY. Matching source RPC names does not prove deployed Identity/Broker parity.
"""
from urllib.parse import urlsplit
from workers import WorkerEntrypoint, Response

_IDENTITY = (
    "resolve_connector_enrollment_consent_for_device",
    "bind_connector_enrollment_challenge",
    "authorize_connector_enrollment_redeem",
)
_BROKER = (
    "gateway_bootstrap_rpc",
    "get_enrollment_binding",
    "verify_enrollment_bootstrap",
    "redeem_enrollment",
    "revoke_binding",
)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        path = urlsplit(str(request.url))
        if (request.method != "GET"
                or path.path != "/__padiem_canary/private-rpc"
                or path.query or path.fragment):
            return Response("NOT_FOUND", status=404)
        try:
            identity = self.env.IDENTITY_AUTHORITY_SERVICE
            broker = self.env.LOCAL_AGENT_BROKER_AUTHORITY_SERVICE
            identity_ok = 0
            broker_ok = 0
            for name in _IDENTITY:
                # Each RPC must cross the actual Workers service binding.
                reply = await getattr(identity, name)({"probe": "nonsecret"})
                if reply != {"ok": False, "error": {"code": "identity_enrollment_disabled"}}:
                    return Response("FAIL_CLOSED", status=503)
                identity_ok += 1
            for name in _BROKER:
                reply = await getattr(broker, name)({"probe": "nonsecret"})
                if reply != {"ok": False, "error": {"code": "broker_enrollment_disabled"}}:
                    return Response("FAIL_CLOSED", status=503)
                broker_ok += 1
            if identity_ok != 3 or broker_ok != 5:
                return Response("FAIL_CLOSED", status=503)
            return Response("LOCAL_RPC_3_IDENTITY_5_BROKER_ALL_DENIED",
                            status=200, headers={"cache-control": "no-store"})
        except Exception:
            # Never print remote exceptions: credentials/errors might be
            # surfaced in a real Service Binding transport.
            return Response("FAIL_CLOSED", status=503)
