from __future__ import annotations

from starlette.routing import Mount, Route, WebSocketRoute

from .connector_status_projection import connectors_status

from .connector_disconnect_routes import (
    disconnect_gmail,
    disconnect_google_calendar,
    disconnect_google_drive,
)

from .github_oauth_routes import (github_start, github_callback, github_status,
                                  github_repositories, github_disconnect, github_pause, github_resume,
                                  github_installation_settings)

from .connector_ticket_routes import google_connector_ticket

from .meeting_drive_upload_routes import MEETING_DRIVE_SESSION_PATH, meeting_drive_upload_session

from .claw_meeting_routes import (
    MEETING_ACTION_PATH, MEETING_ACTIONS_PATH, MEETING_ARTIFACT_PATH, MEETING_END_PATH,
    MEETING_PATH, MEETINGS_PATH,
    claw_meeting_action, claw_meeting_action_create, claw_meeting_artifact,
    claw_meeting_detail, claw_meeting_end, claw_meetings,
)

from .b66_drive_routes import (
    b66_drive_connect,
    b66_drive_connect_callback_return,
    b66_drive_disconnect,
    b66_drive_status,
)

from .calendar_read_activation_routes import activate_google_calendar_read

def register_connector_routes(routes: list) -> None:
    routes.extend([
        Route("/api/connectors/google/ticket", google_connector_ticket, methods=["POST"]),
        Route(MEETING_DRIVE_SESSION_PATH, meeting_drive_upload_session, methods=["POST"]),
        Route(MEETINGS_PATH, claw_meetings, methods=["GET", "POST"]),
        Route(MEETING_PATH, claw_meeting_detail, methods=["GET", "PATCH", "DELETE"]),
        Route(MEETING_END_PATH, claw_meeting_end, methods=["POST"]),
        Route(MEETING_ARTIFACT_PATH, claw_meeting_artifact, methods=["POST"]),
        Route(MEETING_ACTIONS_PATH, claw_meeting_action_create, methods=["POST"]),
        Route(MEETING_ACTION_PATH, claw_meeting_action, methods=["PATCH", "DELETE"]),
        Route("/api/connectors/google/calendar/activate-read", activate_google_calendar_read, methods=["POST"]),
        Route("/api/connectors/status", connectors_status, methods=["GET"]),
        Route("/api/connectors/google/drive/disconnect", disconnect_google_drive, methods=["POST"]),
        Route("/api/connectors/google/gmail/disconnect", disconnect_gmail, methods=["POST"]),
        Route(
            "/api/connectors/google/calendar/disconnect",
            disconnect_google_calendar,
            methods=["POST"],
        ),
        Route("/api/b66/drive/status", b66_drive_status, methods=["GET"]),
        Route("/api/b66/drive/connect", b66_drive_connect, methods=["POST"]),
        Route("/api/b66/drive/connect/callback", b66_drive_connect_callback_return, methods=["GET"]),
        Route("/api/b66/drive/disconnect", b66_drive_disconnect, methods=["POST"]),
        Route("/api/connectors/github/start", github_start, methods=["GET"]),
        Route("/api/connectors/github/callback", github_callback, methods=["GET"]),
        Route("/api/connectors/github/status", github_status, methods=["GET"]),
        Route("/api/connectors/github/installations", github_installation_settings, methods=["GET"]),
        Route("/api/connectors/github/repositories", github_repositories, methods=["GET"]),
        Route("/api/connectors/github/disconnect", github_disconnect, methods=["POST"]),
        Route("/api/connectors/github/pause", github_pause, methods=["POST"]),
        Route("/api/connectors/github/resume", github_resume, methods=["POST"]),
    ])
