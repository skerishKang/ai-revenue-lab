from __future__ import annotations

def register_shared_auth_comparison_routes(routes: list, shared_auth_comparison_flow) -> None:
    # Only explicitly injected test flows expose comparison routes.
    if shared_auth_comparison_flow is not None:
        routes[0:0] = shared_auth_comparison_flow.routes(enabled=True)
