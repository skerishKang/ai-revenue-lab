from __future__ import annotations

import hashlib
from typing import Protocol


class RoutePreviewPort(Protocol):
    def preview(self, *, task: str, route: str) -> dict[str, object]: ...


class DeterministicBusiness14Preview:
    """Network-free B14 consumer adapter used until a trusted live path is wired.

    This adapter never selects providers, resolves credentials, performs fallback,
    or calls a model. Those remain Business 14 authority.
    """

    def preview(self, *, task: str, route: str) -> dict[str, object]:
        canonical_route = "b14/auto" if route in {"business14/auto", "b14/auto"} else route
        digest = hashlib.sha256(f"{canonical_route}\0{task}".encode("utf-8")).hexdigest()[:12]
        return {
            "adapter": "business14-deterministic-mock",
            "route": canonical_route,
            "request_id": f"kagent_{digest}",
            "status": "resolved_not_called",
            "provider_mode": "mock",
            "network_called": False,
        }
