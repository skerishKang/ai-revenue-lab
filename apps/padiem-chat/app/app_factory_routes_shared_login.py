from __future__ import annotations

def register_shared_login_routes(routes: list, shared_login_flow) -> None:
    if shared_login_flow is not None:
        routes[0:0] = shared_login_flow.login_routes()
