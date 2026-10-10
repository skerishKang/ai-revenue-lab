"""Real Workerd/Pyodide multiplex for the four original runtime probes.

Each case delegates the original WorkerEntrypoint.fetch() with the *real*
incoming Workers Request. Only the /probe?case=... routing is new. Keep P01
last in the single-process runner: its existing synthetic route test patches
module globals and must not influence the HTTP/R2 contract probes.
"""
from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from workers import Response, WorkerEntrypoint
from worker_runtime_timeout_probe import Default as TimeoutProbe
from worker_runtime_web_transport_probe import Default as WebTransportProbe
from worker_runtime_r2_read_probe import Default as R2ReadProbe
from worker_runtime_p01_binding_probe import Default as P01BindingProbe


PROBES = {
    "timeout": TimeoutProbe.fetch,
    "web_transport": WebTransportProbe.fetch,
    "r2_read": R2ReadProbe.fetch,
    "p01_binding": P01BindingProbe.fetch,
}


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        url = urlparse(str(request.url))
        if url.path == "/ready" and not url.query:
            return Response("ok", status=200)
        if url.path != "/probe":
            return Response("not found", status=404)
        try:
            params = parse_qs(url.query, strict_parsing=True)
        except ValueError:
            return Response("invalid probe case", status=400)
        if set(params) != {"case"} or len(params["case"]) != 1:
            return Response("invalid probe case", status=400)
        handler = PROBES.get(params["case"][0])
        if handler is None:
            return Response("invalid probe case", status=400)
        # The old handlers inspect only request.url (the path remains /probe).
        # Passing the original real Workerd Request preserves the exact
        # JS-object/Request transport assertions in each legacy probe.
        return await handler(None, request)
