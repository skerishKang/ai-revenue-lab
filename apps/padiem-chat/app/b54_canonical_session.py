"""Server-only producer of one canonical B54 (padiem-claw) auth session (#2964).

This is the production-callable source of the B54 canonical session.  Its input is
an already server-authenticated B54 owner, never a request payload:

```text
server password authentication (D1 users + password_credentials rows)
  -> B54ServerAuthenticatedOwner          (server rows only)
  -> TrustedB54ServerAuthEvidence         (provider/time fixed by this module)
  -> bridge_trusted_b54_server_auth()     (canonical Control Plane authority)
  -> B54BridgedIdentitySession            (product=b54-padiem-claw, tenant-bearing)
```

The five identity fields the Engine resolves a request from — ``product_user_id``,
``provider_subject``, ``subject_id``, ``tenant_id``, ``product_id`` — plus the
canonical session id are never read from a query, JSON body, or cookie payload:

* ``product_user_id`` and ``provider_subject`` are columns of the server's own
  credential rows (``B54ServerAuthenticatedOwner.from_password_credential``);
* ``provider`` and the session lifetime are fixed by this module and by
  ``Settings.session_max_age_seconds``;
* ``product_id`` is pinned to ``B54_PRODUCT_ID`` inside the bridge;
* ``subject_id`` and ``tenant_id`` are minted/resolved by the Control Plane.

``kagent`` (the B54 product source) mints no canonical identity or sessions, so this
bridge stays the single canonical producer and the Control Plane stays the single
session store.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from padiem_control_plane.b54_identity_bridge import (
    B54_SERVER_AUTH_PROVIDER_GOOGLE,
    B54_SERVER_AUTH_PROVIDER_PASSWORD,
    TRUSTED_B54_SERVER_AUTH_PROVIDERS,
    B54BridgedIdentitySession,
    TrustedB54ControlPlaneIdentityAuthority,
    TrustedB54ServerAuthEvidence,
    bridge_trusted_b54_server_auth,
    resolve_current_b54_canonical_session as resolve_current_b54_canonical_session_from_authority,
)

from .history import PasswordCredential

__all__ = [
    "B54CanonicalSessionProducer",
    "B54ServerAuthenticatedOwner",
    "B54_SERVER_AUTH_PROVIDERS",
    "b54_canonical_session_producer",
    "resolve_current_b54_canonical_session",
]

# The reviewed B54 server auth providers (#3240). ``password`` is the original
# path; ``google`` is the verified-OAuth path. Both come from the Control Plane
# bridge's closed allowlist, so neither can be widened by a caller.
B54_SERVER_AUTH_PROVIDER = B54_SERVER_AUTH_PROVIDER_PASSWORD
B54_SERVER_AUTH_PROVIDERS = TRUSTED_B54_SERVER_AUTH_PROVIDERS


def _server_clock() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class B54ServerAuthenticatedOwner:
    """A B54 owner proven by the server's own authentication.

    There is no public constructor path from request content. Instances are built
    by one of the two trusted constructors, each of which accepts only values the
    server itself verified:

    * :meth:`from_password_credential` — the ``users`` / ``password_credentials``
      rows the server read to verify a password login;
    * :meth:`from_verified_google_identity` — the server-side OAuth code exchange
      result, whose userinfo response already refused any unverified email.
    """

    product_user_id: str
    provider_subject: str
    provider: str = B54_SERVER_AUTH_PROVIDER_PASSWORD

    @classmethod
    def from_password_credential(
        cls, credential: PasswordCredential
    ) -> "B54ServerAuthenticatedOwner":
        if not isinstance(credential, PasswordCredential):
            raise ValueError("a server-read password credential is required")
        return cls(
            product_user_id=credential.user.id,
            provider_subject=credential.username,
            provider=B54_SERVER_AUTH_PROVIDER_PASSWORD,
        )

    @classmethod
    def from_verified_google_identity(
        cls,
        *,
        product_user_id: str,
        google_identity: Mapping[str, str],
    ) -> "B54ServerAuthenticatedOwner":
        """Build a B54 owner from a server-verified Google login (#3240).

        ``google_identity`` is the dict returned by
        ``GoogleOAuthClient.fetch_userinfo``, which raises
        ``auth_identity_unverified`` unless the response carried
        ``verified_email is true`` together with a subject and an email. Its
        ``subject`` is therefore already the server-verified Google subject.

        Only ``subject`` is carried forward: the email, name, picture and the raw
        access token are deliberately not part of this owner, and neither the
        token nor any browser-supplied value can reach the B54 bridge.
        """
        if not isinstance(google_identity, Mapping):
            raise ValueError("a server-verified Google identity is required")
        subject = google_identity.get("subject")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 255:
            raise ValueError("a server-verified Google subject is required")
        return cls(
            product_user_id=product_user_id,
            provider_subject=subject,
            provider=B54_SERVER_AUTH_PROVIDER_GOOGLE,
        )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.product_user_id, str)
            or not self.product_user_id.startswith("usr_")
            or len(self.product_user_id) > 80
        ):
            raise ValueError("product_user_id must be a bounded server-assigned identifier")
        if (
            not isinstance(self.provider_subject, str)
            or not self.provider_subject.strip()
            or len(self.provider_subject) > 255
        ):
            raise ValueError("provider_subject must be a bounded server-stored subject")
        if self.provider not in B54_SERVER_AUTH_PROVIDERS:
            raise ValueError("provider must be a reviewed B54 server auth provider")


class B54CanonicalSessionProducer:
    """Establish the canonical B54 session for an already server-authenticated owner."""

    def __init__(
        self,
        *,
        authority: TrustedB54ControlPlaneIdentityAuthority | None,
        session_max_age_seconds: int,
        clock: Callable[[], datetime] = _server_clock,
    ) -> None:
        if isinstance(session_max_age_seconds, bool) or session_max_age_seconds < 1:
            raise ValueError("session_max_age_seconds must be a positive lifetime")
        self._authority = authority
        self._max_age = timedelta(seconds=int(session_max_age_seconds))
        self._clock = clock

    async def establish(
        self, owner: B54ServerAuthenticatedOwner
    ) -> B54BridgedIdentitySession:
        """Turn verified server authentication into the canonical B54 session.

        The authentication window is derived here from the server clock and the
        reviewed session lifetime, so no caller can widen or backdate the scope of
        the canonical session it asks the Control Plane to establish.

        The provider comes from the already server-verified owner, never from the
        request. ``product_id`` stays pinned to ``B54_PRODUCT_ID`` inside the
        bridge, so a Google login can never reuse a B62 session.
        """
        if not isinstance(owner, B54ServerAuthenticatedOwner):
            raise ValueError("a server-authenticated B54 owner is required")
        authenticated_at = self._clock()
        evidence = TrustedB54ServerAuthEvidence(
            product_user_id=owner.product_user_id,
            provider=owner.provider,
            provider_subject=owner.provider_subject,
            authenticated_at=authenticated_at,
            expires_at=authenticated_at + self._max_age,
        )
        return await bridge_trusted_b54_server_auth(
            self._authority,
            evidence,
            now=authenticated_at,
        )


def b54_canonical_session_producer(
    *,
    app_state: Any,
    session_max_age_seconds: int,
) -> B54CanonicalSessionProducer:
    """Build the producer from the Worker's already-trusted Control Plane binding.

    The authority is the same private Service Binding adapter the B62 bridge uses;
    B54 adds a product scope, never a second identity authority or session store.
    """

    authority: TrustedB54ControlPlaneIdentityAuthority | None = getattr(
        app_state, "control_plane_identity_authority", None
    )
    return B54CanonicalSessionProducer(
        authority=authority,
        session_max_age_seconds=session_max_age_seconds,
    )


async def resolve_current_b54_canonical_session(
    request: Any,
) -> B54BridgedIdentitySession | None:
    """Resolve the current active B54 session for the signed-in user (#3243).

    The Web-request entry point for B54 session authority. Exactly one value
    comes from the request — the product user id, read from the signed Padiem
    session cookie by :func:`current_user_id` — and the product is pinned to
    ``b54-padiem-claw`` here on the server.

    Nothing else is read from the request. Every other identity field is
    resolved inside the Control Plane, so query, body, and header values cannot
    select a session, a user, or a product.

    Returns ``None`` when the caller is signed out, when no private Control Plane
    binding is present, or when no B54 session is currently active. The resolved
    session is returned to server code only and is never projected to the
    browser.
    """

    authority = getattr(request.app.state, "control_plane_identity_authority", None)
    if authority is None:
        return None
    # Imported here: auth_routes imports this module, so a module-level import
    # would be circular. The helper pair is the same server-side auth boundary
    # the password and Google B54 chains already use.
    from .auth_routes import auth_ready, current_user_id

    uid = current_user_id(request) if auth_ready(request) else None
    if not uid:
        return None
    try:
        return await resolve_current_b54_canonical_session_from_authority(
            authority, uid
        )
    except Exception:
        return None
