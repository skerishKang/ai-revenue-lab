"""#7261: one Calendar session resolution shared by every calendar path.

Five surfaces need to know *which* canonical session a Calendar decision is
made for, and before this module each of them resolved it on its own:

* ``connector_status_projection`` (``/api/connectors/status``) read the shadow
  pointer directly;
* ``calendar_read_activation_routes`` went through the authoritative resolver
  (``resolve_refreshed_session``, the #7247 B62 shadow contract);
* ``connector_disconnect_routes`` read the shadow pointer directly;
* ``chat_connector_tools`` (the model-turn tool offer) inherited the status
  path;
* the Engine READ lane dispatched with no chat-side session resolution at all.

Two different readings of the same account is exactly how a workspace could be
"active" on the connection screen and "not connected" in the chat turn. Every
path now calls :func:`resolve_calendar_session` and nothing else; a single log
line names the path, the product the session was read as, and the verdict, so
the next mismatch is visible in the journal without guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from .auth_routes import auth_ready, current_user_id
from .control_plane_identity import IdentityBridgeError
from .control_plane_identity_shadow import (
    request_canonical_session_id,
    resolve_refreshed_session,
)
from .journal_host import ensure_journal_visible

_LOG = logging.getLogger(__name__)

# The serving host configures no logging, so an application INFO record would be
# created and dropped. Every stage line this module exists for has to arrive.
ensure_journal_visible(_LOG)

#: The reviewed calendar paths. A caller that is not in this set is a
#: programming error, never a silent fallback. ``account_delete`` (#7557) is
#: the withdrawal reading the workspace whose Google grants it must purge.
CALENDAR_PATH_STATUS = "status"
CALENDAR_PATH_ACTIVATION = "activation"
CALENDAR_PATH_DISCONNECT = "disconnect"
CALENDAR_PATH_TOOL_GRANT = "tool_grant"
CALENDAR_PATH_READ = "read"
CALENDAR_PATH_ACCOUNT_DELETE = "account_delete"
CALENDAR_SESSION_PATHS = frozenset({
    CALENDAR_PATH_STATUS,
    CALENDAR_PATH_ACTIVATION,
    CALENDAR_PATH_DISCONNECT,
    CALENDAR_PATH_TOOL_GRANT,
    CALENDAR_PATH_READ,
    CALENDAR_PATH_ACCOUNT_DELETE,
})

# Unresolved verdicts. Each one is a closed label: no identifier, no token.
CALENDAR_SESSION_NO_TRUSTED_AUTHORITY = "no_trusted_authority"
CALENDAR_SESSION_NOT_LINKED = "identity_not_linked"
CALENDAR_SESSION_INACTIVE = "session_inactive"
CALENDAR_SESSION_REJECTED = "session_rejected"
CALENDAR_SESSION_UNAVAILABLE = "truth_unavailable"


@dataclass(frozen=True, slots=True)
class CalendarSession:
    """The one canonical session every calendar path must agree on."""

    path: str
    session_id: str | None = None
    product_id: str | None = None
    subject_present: bool = False
    reason: str | None = None

    @property
    def resolved(self) -> bool:
        return self.reason is None and isinstance(self.session_id, str) and bool(self.session_id)


def _verdict_for_error(exc: IdentityBridgeError) -> str:
    """Map one bridge refusal onto a closed calendar verdict.

    ``control_plane_identity_not_linked`` is a browser-session answer (the
    product user has no canonical link), while a real authority fault is a
    service answer. They must not collapse into one label.
    """

    code = getattr(exc, "code", "")
    status = getattr(exc, "status_code", 503)
    if code == "control_plane_identity_not_linked":
        return CALENDAR_SESSION_NOT_LINKED
    if code == "control_plane_session_inactive":
        return CALENDAR_SESSION_INACTIVE
    if status >= 500:
        return CALENDAR_SESSION_UNAVAILABLE
    return CALENDAR_SESSION_REJECTED


async def _value(value: Any) -> Any:
    import inspect

    return await value if inspect.isawaitable(value) else value


async def resolve_calendar_session(
    request: Any,
    *,
    path: str,
    user_id: str | None = None,
) -> CalendarSession:
    """Resolve the canonical session one calendar surface must use.

    Fails closed at every step and never raises: a caller receives an
    unresolved :class:`CalendarSession` carrying the closed reason instead.
    The single journal line names the path, the product label the authority
    returned and the verdict only — never a session id, subject or token.
    """

    if path not in CALENDAR_SESSION_PATHS:
        raise ValueError(f"unknown calendar session path: {path!r}")

    def _verdict(reason: str | None, *, product: str | None = None) -> CalendarSession:
        _LOG.info(
            "calendar_session path=%s verdict=%s product=%s",
            path,
            reason or "ok",
            product or "-",
        )
        return CalendarSession(path=path, product_id=product, reason=reason)

    try:
        if not auth_ready(request):
            return _verdict(CALENDAR_SESSION_NO_TRUSTED_AUTHORITY)
        uid = user_id if isinstance(user_id, str) and user_id else current_user_id(request)
        if not uid:
            return _verdict(CALENDAR_SESSION_NO_TRUSTED_AUTHORITY)
        history_store = getattr(request.app.state, "history_store", None)
        if history_store is None:
            return _verdict(CALENDAR_SESSION_NO_TRUSTED_AUTHORITY)
        profile = await _value(history_store.get_user(uid))
    except Exception:  # noqa: BLE001 - product authentication could not be evaluated
        return _verdict(CALENDAR_SESSION_UNAVAILABLE)
    if profile is None:
        return _verdict(CALENDAR_SESSION_NO_TRUSTED_AUTHORITY)

    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    shadow_store = getattr(request.app.state, "identity_shadow_store", None)
    if authority is None or shadow_store is None:
        return _verdict(CALENDAR_SESSION_UNAVAILABLE)

    try:
        current_session = await resolve_refreshed_session(
            authority=authority,
            store=shadow_store,
            product_user_id=uid,
            current_session_id=request_canonical_session_id(request),
        )
    except IdentityBridgeError as exc:
        return _verdict(_verdict_for_error(exc))
    except Exception:  # noqa: BLE001 - an authority fault is never a session
        return _verdict(CALENDAR_SESSION_UNAVAILABLE)

    session_id = getattr(current_session, "session_id", None)
    if not isinstance(session_id, str) or not session_id:
        return _verdict(CALENDAR_SESSION_REJECTED)
    product_id = getattr(current_session, "product_id", None)
    subject = getattr(current_session, "subject", None)
    subject_id = getattr(subject, "subject_id", None)

    verdict = _verdict(None, product=product_id if isinstance(product_id, str) else None)
    return CalendarSession(
        path=verdict.path,
        session_id=session_id,
        product_id=verdict.product_id,
        subject_present=bool(subject_id),
        reason=None,
    )
