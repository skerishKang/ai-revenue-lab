from __future__ import annotations

from workers import Response, WorkerEntrypoint

from padiem_control_plane.contact_verification_rpc import ContactVerificationRpcFacade


class Default(WorkerEntrypoint):
    """Internal-only RPC entrypoint for canonical Padiem contact verification."""

    def _facade(self) -> ContactVerificationRpcFacade:
        pepper = str(self.env.CONTACT_VERIFICATION_PEPPER).encode("utf-8")
        return ContactVerificationRpcFacade(pepper=pepper)

    async def issue(self, payload: dict) -> dict:
        return self._facade().issue(payload)

    async def resend(self, payload: dict) -> dict:
        return self._facade().resend(payload)

    async def verify(self, payload: dict) -> dict:
        return self._facade().verify(payload)

    async def fetch(self, request):
        # The OTP core is intentionally not a public HTTP API. Product Workers
        # call this Worker only through a same-account Service Binding RPC.
        return Response(
            "Not Found",
            status=404,
            headers={"cache-control": "no-store"},
        )
