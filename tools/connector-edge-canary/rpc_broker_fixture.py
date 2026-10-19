"""Test-only canonical Broker WorkerEntrypoint RPC shape.

NEVER deployed; no Durable Object, credentials, enrollment, nonce or tokens.
The gateway tests actual cross-Worker method transport, not authorization.
"""
from workers import WorkerEntrypoint, Response

_DENIAL = {"ok": False, "error": {"code": "broker_enrollment_disabled"}}


class Default(WorkerEntrypoint):
    async def gateway_bootstrap_rpc(self, payload):
        return _DENIAL

    async def get_enrollment_binding(self, payload):
        return _DENIAL

    async def verify_enrollment_bootstrap(self, payload):
        return _DENIAL

    async def redeem_enrollment(self, payload):
        return _DENIAL

    async def revoke_binding(self, payload):
        return _DENIAL

    async def fetch(self, request):
        return Response("NOT_FOUND", status=404)
