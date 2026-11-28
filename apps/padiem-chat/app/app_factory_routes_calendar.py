from __future__ import annotations

from starlette.routing import Mount, Route, WebSocketRoute

from .calendar_routes import (
    calendar_appointments_create,
    calendar_appointment_manage,
    calendar_work_log_manage,
    calendar_appointments_list,
    calendar_item_detail,
    calendar_items,
    calendar_today,
    calendar_upcoming,
    calendar_work_logs_create,
    calendar_work_logs_list,
)

def register_calendar_routes(routes: list) -> None:
    routes.extend([
        Route("/api/calendar/today", calendar_today, methods=["GET"]),
        Route("/api/calendar/upcoming", calendar_upcoming, methods=["GET"]),
        Route("/api/calendar/items", calendar_items, methods=["GET"]),
        Route(
            "/api/calendar/items/{calendar_item_id}",
            calendar_item_detail,
            methods=["GET"],
        ),
        Route("/api/calendar/work-logs", calendar_work_logs_list, methods=["GET"]),
        Route("/api/calendar/work-logs", calendar_work_logs_create, methods=["POST"]),
        Route("/api/calendar/appointments", calendar_appointments_list, methods=["GET"]),
        Route("/api/calendar/appointments", calendar_appointments_create, methods=["POST"]),
        Route("/api/calendar/appointments/{appointment_id}", calendar_appointment_manage, methods=["PUT","DELETE"]),
        Route("/api/calendar/work-logs/{log_id}", calendar_work_log_manage, methods=["PUT","DELETE"]),
    ])
