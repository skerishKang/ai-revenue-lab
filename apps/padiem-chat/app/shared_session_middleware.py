"""Attach only a verified common-session identity; the legacy guard still runs."""
from starlette.requests import Request

from .shared_auth_adapter import SharedAuthUnavailable
from .shared_login_flow import ACCESS_COOKIE


class SharedSessionMiddleware:
    def __init__(self, app, *, flow):
        self.app, self.flow = app, flow

    async def __call__(self, scope, receive, send):
        if scope.get('type') == 'http' and self.flow is not None:
            request = Request(scope)
            token = request.cookies.get(ACCESS_COOKIE)
            if token:
                try:
                    user = await self.flow.auth.user_id(request, token)
                    if isinstance(user, str) and user:
                        scope.setdefault('state', {})['padiem_shared_user_id'] = user
                except SharedAuthUnavailable:
                    pass
        await self.app(scope, receive, send)
