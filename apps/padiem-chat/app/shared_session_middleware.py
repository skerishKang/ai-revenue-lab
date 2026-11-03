"""Attach only a verified common-session identity; the legacy guard still runs."""
import logging
import time

from starlette.requests import Request

from .shared_auth_adapter import SharedAuthUnavailable
from .shared_login_flow import ACCESS_COOKIE
from .request_timing import measure


class SharedSessionMiddleware:
    def __init__(self, app, *, flow):
        self.app, self.flow = app, flow

    async def __call__(self, scope, receive, send):
        if scope.get('type') == 'http' and self.flow is not None:
            request = Request(scope)
            token = request.cookies.get(ACCESS_COOKIE)
            if token:
                from .request_telemetry import current_request_id
                from .shared_login_timing import (
                    begin_login_timings, emit_identity_timing, end_login_timings,
                    record_login_timing,
                )
                token_context, details = begin_login_timings()
                started = time.perf_counter()
                request_id = current_request_id()
                try:
                    try:
                        with measure('auth'):
                            user = await self.flow.auth.user_id(request, token)
                        if isinstance(user, str) and user:
                            scope.setdefault('state', {})['padiem_shared_user_id'] = user
                    except SharedAuthUnavailable:
                        logging.getLogger(__name__).warning(
                            "shared_session_verification_or_identity_lookup_failed")
                finally:
                    record_login_timing('shared_identity_lookup',
                                        (time.perf_counter() - started) * 1000)
                    emit_identity_timing(request_id, started, details)
                    end_login_timings(token_context)
        await self.app(scope, receive, send)
