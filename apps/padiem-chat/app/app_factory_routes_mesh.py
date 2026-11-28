from __future__ import annotations

from starlette.routing import Mount, Route, WebSocketRoute

def register_oracle_mesh_routes(routes: list, oracle_mesh_return_source) -> None:
    # #4139 Oracle management-host return legs: owner intent, executor
    # poll, executor submit. Verified server-side and appended through
    # the existing history authority. Mounted solely when the deployment
    # composes the ownership map plus channel secret; the default app has
    # no such routes.
    #
    # This gate used to sit inside the owner-enrollment block. It cannot: the
    # COM2 host composes the map+secret (the mesh lane runs there) but has no
    # canonical Identity+Broker private ports, so every Engine-signed lane
    # (desktop, PC-files, PC-browser, mesh returns) stayed unmounted and died
    # at the static catch-all with 405. Each route here is still fail-closed on
    # its own authority — the ownership source, the Engine desktop proof, or
    # the canonical owner session — so mounting them is not an opening.
    if oracle_mesh_return_source is not None:
        from .oracle_mesh_read_return_routes import (
            ORACLE_MESH_READ_BUSY_PATH,
            ORACLE_MESH_READ_LANE_STATUS_PATH,
            ORACLE_MESH_READ_CANCEL_PATH,
            ORACLE_MESH_READ_CANCEL_POLL_PATH,
            ORACLE_MESH_READ_ORIGINAL_PATH,
            ORACLE_MESH_READ_POLL_PATH,
            ORACLE_MESH_READ_REQUEST_PATH,
            ORACLE_MESH_READ_RESULT_PATH,
            oracle_chat_engine_pc_drive_call,
            oracle_mesh_engine_chat_files_call,
            oracle_mesh_engine_claw_files_call,
            oracle_mesh_read_busy_check,
            oracle_mesh_read_lane_status,
            oracle_mesh_read_cancel_check,
            oracle_mesh_read_cancel_poll,
            oracle_mesh_read_original,
            oracle_mesh_read_poll,
            oracle_mesh_read_request,
            oracle_mesh_engine_desktop_call,
            oracle_mesh_read_result,
        )
        from .claw_pc_browser_routes import (
            BROWSER_CAPTURE_PATH, browser_capture,
            oracle_mesh_engine_claw_browser_call,
            oracle_mesh_engine_chat_browser_call,
        )
        # #5997: the executor renews a live claim while a long command runs.
        from .oracle_mesh_lease_renew_routes import (
            ORACLE_MESH_READ_RENEW_PATH,
            oracle_mesh_read_renew,
        )
        routes[-1:-1] = [
            Route(ORACLE_MESH_READ_REQUEST_PATH, oracle_mesh_read_request, methods=["POST"]),
            Route("/internal/claw/engine-desktop", oracle_mesh_engine_desktop_call, methods=["POST"]),
            Route("/internal/claw/engine-pc-drive", oracle_mesh_engine_desktop_call, methods=["POST"]),
            Route("/internal/claw/engine-pc-files", oracle_mesh_engine_claw_files_call, methods=["POST"]),
            Route("/internal/claw/engine-pc-browser", oracle_mesh_engine_claw_browser_call, methods=["POST"]),
            Route("/internal/chat/engine-pc-drive", oracle_chat_engine_pc_drive_call, methods=["POST"]),
            Route("/internal/chat/engine-pc-files", oracle_mesh_engine_chat_files_call, methods=["POST"]),
            Route("/internal/chat/engine-pc-browser", oracle_mesh_engine_chat_browser_call, methods=["POST"]),
            Route(BROWSER_CAPTURE_PATH, browser_capture, methods=["GET"]),
            Route(ORACLE_MESH_READ_POLL_PATH, oracle_mesh_read_poll, methods=["POST"]),
            Route(ORACLE_MESH_READ_RESULT_PATH, oracle_mesh_read_result, methods=["POST"]),
            Route(ORACLE_MESH_READ_CANCEL_PATH, oracle_mesh_read_cancel_check, methods=["POST"]),
            Route(ORACLE_MESH_READ_CANCEL_POLL_PATH, oracle_mesh_read_cancel_poll, methods=["POST"]),
            Route(ORACLE_MESH_READ_BUSY_PATH, oracle_mesh_read_busy_check, methods=["POST"]),
            Route(ORACLE_MESH_READ_LANE_STATUS_PATH, oracle_mesh_read_lane_status, methods=["POST"]),
            Route(ORACLE_MESH_READ_RENEW_PATH, oracle_mesh_read_renew, methods=["POST"]),
            Route(ORACLE_MESH_READ_ORIGINAL_PATH, oracle_mesh_read_original, methods=["GET"]),
        ]
