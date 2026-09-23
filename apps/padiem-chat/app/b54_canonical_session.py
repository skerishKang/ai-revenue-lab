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

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from padiem_control_plane.b54_identity_bridge import (
    B54BridgedIdentitySession,
    TrustedB54ControlPlaneIdentityAuthority,
    TrustedB54ServerAuthEvidence,
    bridge_trusted_b54_server_auth,
)

from .history import PasswordCredential

__all__ = [
    "B54CanonicalSessionProducer",
    "B54ServerAuthenticatedOwner",
    "b54_canonical_session_producer",
]

# The only reviewed B54 server auth provider. OAuth is B62-only, and
# TrustedB54ServerAuthEvidence rejects any other value.
B54_SERVER_AUTH_PROVIDER = "password"


def _server_clock() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class B54ServerAuthenticatedOwner:
    """A B54 owner proven by the server's own authentication rows.

    There is no public constructor path from request content: instances are built
    by :meth:`from_password_credential` from the ``users`` / ``password_credentials``
    rows the server read to verify the login.
    """

    product_user_id: str
    provider_subject: str

    @classmethod
    def from_password_credential(
        cls, credential: PasswordCredential
    ) -> "B54ServerAuthenticatedOwner":
        if not isinstance(credential, PasswordCredential):
            raise ValueError("a server-read password credential is required")
        return cls(
            product_user_id=credential.user.id,
            provider_subject=credential.username,
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
        """
        if not isinstance(owner, B54ServerAuthenticatedOwner):
            raise ValueError("a server-authenticated B54 owner is required")
        authenticated_at = self._clock()
        evidence = TrustedB54ServerAuthEvidence(
            product_user_id=owner.product_user_id,
            provider=B54_SERVER_AUTH_PROVIDER,
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
