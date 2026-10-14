"""Optional CP-owned voice capability policy; never activated by default.

This is *not* a product entitlement decision. Only an explicit, separately
approved and deployed immutable tenant/product policy may produce voice grants.
No account, browser, client claim, or generic orchestration grant can opt in.
The current Engine admission Worker does not supply such a policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import re

from .auth_sessions import AuthSessionSnapshot
from .contracts import ControlPlaneContractError, SubjectType
from .entitlements import EntitlementGrant

VOICE_STT_CAPABILITIES = frozenset({
    "voice.stt.transcribe",
    "voice.stt.live_token",
})
VOICE_STT_PRODUCTS = frozenset({"b62", "b54-padiem-claw"})
MAX_VOICE_STT_POLICY_UNITS = 1_000_000  # technical upper bound, not approved allowance
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _invalid(message: str) -> ControlPlaneContractError:
    return ControlPlaneContractError("invalid_voice_stt_policy", message)


def _time(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise _invalid(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class VoiceSttTenantScope:
    """One explicitly approved product + canonical tenant + bounded capabilities."""

    product_id: str
    tenant_id: str
    unit_limits: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if self.product_id not in VOICE_STT_PRODUCTS:
            raise _invalid("product is not an approved voice scope")
        if not isinstance(self.tenant_id, str) or not _ID.fullmatch(self.tenant_id):
            raise _invalid("canonical tenant is required")
        if self.tenant_id == self.product_id:
            raise _invalid("tenant must not alias product")
        if not isinstance(self.unit_limits, tuple) or not self.unit_limits:
            raise _invalid("explicit bounded capability units are required")
        observed: set[str] = set()
        for item in self.unit_limits:
            if not isinstance(item, tuple) or len(item) != 2:
                raise _invalid("capability limit must be a pair")
            key, units = item
            if key not in VOICE_STT_CAPABILITIES or key in observed:
                raise _invalid("unknown or repeated voice capability")
            if isinstance(units, bool) or not isinstance(units, int) or not 1 <= units <= MAX_VOICE_STT_POLICY_UNITS:
                raise _invalid("capability units must be explicitly positive and bounded")
            observed.add(key)


@dataclass(frozen=True, slots=True)
class VoiceSttPolicy:
    """Trusted immutable review input, NOT browser JSON or an implicit default."""

    revision: str
    effective_at: datetime
    expires_at: datetime
    scopes: tuple[VoiceSttTenantScope, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.revision, str) or not _ID.fullmatch(self.revision):
            raise _invalid("explicit policy revision required")
        if _time(self.expires_at, "expires_at") <= _time(self.effective_at, "effective_at"):
            raise _invalid("invalid policy lifetime")
        if not isinstance(self.scopes, tuple) or not self.scopes or len(self.scopes) > 128:
            raise _invalid("approved scopes must be finite and nonempty")
        seen: set[tuple[str, str]] = set()
        for scope in self.scopes:
            if not isinstance(scope, VoiceSttTenantScope):
                raise _invalid("scope must be a reviewed VoiceSttTenantScope")
            identity = (scope.product_id, scope.tenant_id)
            if identity in seen:
                raise _invalid("duplicate product/tenant authority")
            seen.add(identity)


def voice_stt_grants_for_session(
    session: AuthSessionSnapshot,
    *,
    policy: VoiceSttPolicy | None,
    now: datetime,
) -> tuple[EntitlementGrant, ...]:
    """Default deny; only a matching active canonical USER session may obtain grants."""
    observed = _time(now, "now")
    if policy is None:
        return ()
    if not isinstance(policy, VoiceSttPolicy) or not isinstance(session, AuthSessionSnapshot):
        raise _invalid("untrusted voice policy or session shape")
    if not (_time(policy.effective_at, "effective_at") <= observed < _time(policy.expires_at, "expires_at")):
        return ()
    if not session.is_active(now=observed) or session.subject.subject_type is not SubjectType.USER:
        return ()
    if not session.tenant_id or session.tenant_id in {session.product_id, session.subject.subject_id}:
        return ()
    for scope in policy.scopes:
        if scope.product_id == session.product_id and scope.tenant_id == session.tenant_id:
            return tuple(EntitlementGrant(key=k, allowed=True, limit=n) for k, n in scope.unit_limits)
    return ()


VOICE_STT_POLICY_INSTALLED_IN_RUNTIME = False
VOICE_STT_DEFAULT_ENTITLEMENT_ALLOW = False
