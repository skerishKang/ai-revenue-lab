"""Who the Designer is serving, and in which tenant.

The Designer has **no independent login authority and no key screen**. It
resolves the caller through PADIEM's existing session contract: the same
signed ``padiem_session`` cookie the B62 product uses, verified by the same
authority that mints it. The authority module is loaded from the B62 product
rather than re-implemented, so the two can never disagree about what a valid
session is.

Tenant separation is explicit. The session cookie proves *who* the caller is;
the tenant a caller works in is a server-side setting, because the session
cookie carries no tenant claim. The status endpoint reports which of the two
modes is actually in force.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from .config import Settings
from .contracts import DesignerError

#: The repo root, derived from this file's location
#: (``<repo>/apps/padiem-designer/app/identity.py``).
REPO_ROOT = Path(__file__).resolve().parents[3]

#: The B62 product package that owns the session authority.
B62_APP_ROOT = REPO_ROOT / "apps" / "padiem-chat"

#: The module name the B62 package is loaded under, so it can never collide
#: with this app's own ``app`` package.
_B62_PACKAGE_NAME = "padiem_chat_app"

#: The module name the B62 session authority is cached under.
_B62_AUTH_MODULE_NAME = "padiem_chat_app.auth"

#: The cookie the B62 session authority owns.
SESSION_COOKIE = "padiem_session"


@dataclass(frozen=True, slots=True)
class DesignerIdentity:
    """The resolved caller."""

    tenant_id: str
    user_id: str
    session_id: str
    auth_mode: str

    def to_public_dict(self) -> dict[str, object]:
        return {
            "tenantId": self.tenant_id,
            "userId": self.user_id,
            "sessionId": self.session_id,
            "authMode": self.auth_mode,
        }


def load_session_authority() -> ModuleType | None:
    """Load the B62 session authority, or return ``None`` when it is absent.

    The B62 package is loaded from its own path under a name of its own, so
    this app's ``app`` package and the B62 ``app`` package never collide. The
    module returned is the B62 ``auth`` module, which is where the session
    cookie contract lives.
    """

    existing = sys.modules.get(_B62_AUTH_MODULE_NAME)
    if existing is not None:
        return existing

    package_dir = B62_APP_ROOT / "app"
    initializer = package_dir / "__init__.py"
    if not initializer.is_file():
        return None

    spec = importlib.util.spec_from_file_location(
        _B62_PACKAGE_NAME,
        initializer,
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_B62_PACKAGE_NAME] = module
    try:
        spec.loader.exec_module(module)
        auth = importlib.import_module(f"{_B62_PACKAGE_NAME}.auth")
    except Exception:  # noqa: BLE001 - an unusable authority is simply absent
        sys.modules.pop(_B62_PACKAGE_NAME, None)
        return None
    sys.modules[_B62_AUTH_MODULE_NAME] = auth
    return auth


def _authority_settings(settings: Settings) -> object:
    """Build the B62 settings object the session authority expects."""

    authority = load_session_authority()
    if authority is None:
        raise DesignerError(
            503,
            "session_authority_unavailable",
            "The PADIEM session authority could not be loaded.",
        )
    config = importlib.import_module(f"{_B62_PACKAGE_NAME}.config")
    try:
        return config.Settings(
            session_secret=settings.b14_session_secret,
            session_max_age_seconds=7 * 24 * 3600,
        )
    except TypeError:
        return config.Settings()


def _decode_claims(authority: ModuleType, authority_settings: object, token: str) -> object | None:
    """Ask the B62 authority for the verified claims of one session cookie.

    The authority exposes the claims object. Its older sibling returns only the
    user id, so that path is used as a fallback rather than re-deriving the
    claim shape here.
    """

    decode_claims = getattr(authority, "decode_session_claims", None)
    if decode_claims is not None:
        return decode_claims(authority_settings, token)
    decode_token = getattr(authority, "decode_session_token", None)
    if decode_token is None:
        raise DesignerError(
            503,
            "session_authority_unavailable",
            "The PADIEM session authority exposes no session decoder.",
        )
    user_id = decode_token(authority_settings, token)
    if not user_id:
        return None
    return _Claims(user_id=user_id, canonical_session_id=None)


@dataclass(frozen=True, slots=True)
class _Claims:
    """The minimal claim shape the Designer reads."""

    user_id: str
    canonical_session_id: str | None


def resolve_identity(
    *,
    session_token: str | None,
    settings: Settings,
) -> DesignerIdentity:
    """Resolve the caller, failing closed when authentication is configured.

    When a session secret is configured the signed cookie is required and the
    B62 authority decides. When no secret is configured the app runs in an
    explicit development mode with the configured tenant, and says so.
    """

    if settings.auth_configured:
        if not session_token:
            raise DesignerError(
                401,
                "session_required",
                "A PADIEM session cookie is required.",
            )
        authority = load_session_authority()
        if authority is None:
            raise DesignerError(
                503,
                "session_authority_unavailable",
                "The PADIEM session authority could not be loaded.",
            )
        try:
            claims = _decode_claims(authority, _authority_settings(settings), session_token)
        except Exception as exc:  # noqa: BLE001 - the authority refuses bad sessions
            raise DesignerError(
                401,
                "session_invalid",
                "The PADIEM session cookie was refused.",
            ) from exc
        if claims is None:
            # The B62 authority answers an unusable cookie with no claims.
            raise DesignerError(
                401,
                "session_invalid",
                "The PADIEM session cookie was refused.",
            )
        tenant = settings.tenant_id or settings.dev_tenant_id
        return DesignerIdentity(
            tenant_id=tenant,
            user_id=claims.user_id,
            session_id=claims.canonical_session_id or claims.user_id,
            auth_mode="padiem_session",
        )

    return DesignerIdentity(
        tenant_id=settings.dev_tenant_id,
        user_id=settings.dev_user_id,
        session_id="dev-session",
        auth_mode="dev_configured",
    )
