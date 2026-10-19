"""Test-only canonical Identity WorkerEntrypoint RPC shape.

NEVER deployed; no Durable Object, session, account, secrets or consent.
Every method must return a bounded synthetic denial.
"""
from workers import WorkerEntrypoint, Response

_DENIAL = {"ok": False, "error": {"code": "identity_enrollment_disabled"}}


class Default(WorkerEntrypoint):
    async def resolve_connector_enrollment_consent_for_device(self, payload):
        return _DENIAL

    async def bind_connector_enrollment_challenge(self, payload):
        return _DENIAL

    async def authorize_connector_enrollment_redeem(self, payload):
        return _DENIAL

    async def fetch(self, request):
        return Response("NOT_FOUND", status=404)
