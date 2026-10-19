"""#4483 S3-A1: final server-side dispatch guard at the provider boundary.

S1 (#4453) produced fail-closed *advice* (``central_model_pre_dispatch_advice``)
plus the host-owned ``VerifiedProductModelSelection``. The missing control is a
final check that runs immediately around the outbound Business 14 request,
*after* any earlier advisory decision and immediately *before* a provider
request can leave the process:

- ``authorize()`` returns an explicit ``FinalDispatchDecision`` and never
  raises, so a caller can surface a precise denial code instead of pretending
  the verification completed;
- ``authorized_service_transport()`` / ``authorized_http_transport()``
  both validate the outbound model payload and raise ``FinalDispatchDenied``
  before B14 transport delegation, so rejected provider POST count stays 0;
- the exact authorized model id is pinned: a payload that targets any other
  model (a fallback, ``b14/auto``, or a catalog swap) is rejected before
  delegation.

Denials are codes, never silent repairs: no fallback model is chosen, no tier
is widened, no missing authority is defaulted. This module is intentionally not
composed into ``app_factory``/``worker`` wiring by #4483 (default-off rollout);
the minimal integration patch is documented in the PR. It never calls a model,
never touches D1 writes, and never changes product/tier policy.
"""
from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx as execution_httpx
from padiem_control_plane.model_assignment_policy import PRODUCTS, TIERS

from .central_model_pre_dispatch_advice import (
    VerifiedProductModelSelection,
    inspect_pre_dispatch_policy,
)

if TYPE_CHECKING:
    from .b14_client import B14ServiceTransport

_CANONICAL_USER = re.compile(r"usr_[a-f0-9]{32}\Z")
_SCOPE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

DENIAL_REASONS = (
    "missing_verified_selection",
    "missing_session_authority",
    "user_binding_mismatch",
    "workspace_binding_mismatch",
    "product_binding_mismatch",
    "tier_binding_mismatch",
    "product_capability_unverified",
    "missing_authorized_revision",
    "policy_revision_changed",
    "dispatch_model_mismatch",
    "final_dispatch_guard_unavailable",
)


@dataclass(frozen=True)
class DispatchSessionContext:
    """Live server-proven session facts; never built from client-supplied values.

    Only a trusted host reader may return this object; its string fields are
    not authentication evidence by themselves. The guard invokes the reader
    again for each outbound attempt, so session revocation after selection
    cannot be hidden behind an unchanged model-policy revision. A reader
    must return None on expiry/revocation/unverified product-tier authority.
    """

    canonical_user_id: str
    workspace_id: str
    product_id: str
    member_tier: str
    product_capability_verified: bool

    def __post_init__(self):
        if not isinstance(self.canonical_user_id, str) or _CANONICAL_USER.fullmatch(self.canonical_user_id) is None:
            raise ValueError("missing_session_authority")
        if not isinstance(self.workspace_id, str) or _SCOPE_ID.fullmatch(self.workspace_id) is None:
            raise ValueError("missing_session_authority")
        if self.product_id not in PRODUCTS - {"central"} or self.member_tier not in TIERS:
            raise ValueError("missing_session_authority")
        if type(self.product_capability_verified) is not bool:
            raise ValueError("missing_session_authority")


@dataclass(frozen=True)
class FinalDispatchDecision:
    """Explicit guard verdict. ``allowed`` is the only dispatch grant."""

    allowed: bool
    reason: str
    revision: int | None
    model_id: str
    product_id: str
    tier: str

    @property
    def enforcement(self) -> str:
        return "final_dispatch_guard"


class FinalDispatchDenied(RuntimeError):
    """Raised inside the B14 dispatch path; the provider request is never sent."""

    def __init__(self, reason: str, *, decision: FinalDispatchDecision | None = None):
        super().__init__(f"final_dispatch_denied:{reason}")
        self.reason = reason
        self.decision = decision


def _selection_facts(selection: Any) -> tuple[str, str, str]:
    if isinstance(selection, VerifiedProductModelSelection):
        return selection.exact_model_id, selection.product_id, selection.tier
    return "", "", ""


class FinalDispatchGuard:
    """Re-checks live authority immediately before the provider call.

    Fail-closed state machine, in order:

    1. a verified selection and a fresh trusted server session reader must exist;
    2. session identities must exactly equal the verified selection
       (user, workspace, product, tier) — a client-supplied tier or a foreign
       identity is a mismatch, never a repair;
    3. capability/P01 must be proven for the live session;
    4. the choice-time policy revision must be present and must still be the
       current D1 revision (fresh snapshot + B14 catalog re-read) at the
       dispatch boundary — a changed policy revision denies with
       ``policy_revision_changed``; revocation/expiry of a user session is
       independently detected by the live reader, never inferred from D1;
    5. the outbound payload must target exactly the authorized model id.
    """

    def __init__(
        self,
        *,
        selection: VerifiedProductModelSelection,
        current_session_reader: Callable[[], Awaitable[DispatchSessionContext | None]] | None,
        store: Any,
        b14_catalog_source: Any,
        authorized_revision: int | None,
    ) -> None:
        self._selection = selection
        self._current_session_reader = current_session_reader
        self._store = store
        self._b14_catalog_source = b14_catalog_source
        self._authorized_revision = authorized_revision
        self._last_decision: FinalDispatchDecision | None = None

    @property
    def exact_model_id(self) -> str:
        return _selection_facts(self._selection)[0]

    @property
    def last_decision(self) -> FinalDispatchDecision | None:
        return self._last_decision

    def _deny(self, reason: str) -> FinalDispatchDecision:
        model_id, product_id, tier = _selection_facts(self._selection)
        return FinalDispatchDecision(False, reason, None, model_id, product_id, tier)

    async def _evaluate(self) -> FinalDispatchDecision:
        try:
            selection = self._selection
            if not isinstance(selection, VerifiedProductModelSelection):
                return self._deny("missing_verified_selection")
            if not callable(self._current_session_reader):
                return self._deny("missing_session_authority")
            try:
                # Re-read the canonical server session at each actual dispatch;
                # a cached login projection cannot prove a still-active owner.
                session = await self._current_session_reader()
            except Exception:
                return self._deny("missing_session_authority")
            if not isinstance(session, DispatchSessionContext):
                return self._deny("missing_session_authority")
            if session.canonical_user_id != selection.canonical_user_id:
                return self._deny("user_binding_mismatch")
            if session.workspace_id != selection.workspace_id:
                return self._deny("workspace_binding_mismatch")
            if session.product_id != selection.product_id:
                return self._deny("product_binding_mismatch")
            if session.member_tier != selection.tier:
                return self._deny("tier_binding_mismatch")
            if session.product_capability_verified is not True:
                return self._deny("product_capability_unverified")
            if type(self._authorized_revision) is not int or self._authorized_revision < 0:
                return self._deny("missing_authorized_revision")
            advice = await inspect_pre_dispatch_policy(
                selection=selection,
                store=self._store,
                b14_catalog_source=self._b14_catalog_source,
                product_capability_verified=True,
            )
            model_id, product_id, tier = _selection_facts(selection)
            if not advice.allowed:
                return FinalDispatchDecision(
                    False, advice.reason, advice.revision, model_id, product_id, tier
                )
            if advice.revision != self._authorized_revision:
                # This detects policy revision drift only. The trusted live
                # session reader is separately responsible for revoked or
                # expired session / product tier assertions.
                return FinalDispatchDecision(
                    False, "policy_revision_changed", advice.revision,
                    model_id, product_id, tier,
                )
            return FinalDispatchDecision(
                True, "allowed", advice.revision, model_id, product_id, tier
            )
        except Exception:
            return self._deny("final_dispatch_guard_unavailable")

    async def authorize(self) -> FinalDispatchDecision:
        """Return the current verdict. Never raises; mutates no external state."""
        decision = await self._evaluate()
        self._last_decision = decision
        return decision

    async def verify_dispatch_payload(
        self, payload: Mapping[str, Any]
    ) -> FinalDispatchDecision:
        """Re-authorize and then pin the outbound payload to the exact model."""
        decision = await self.authorize()
        if not decision.allowed:
            raise FinalDispatchDenied(decision.reason, decision=decision)
        model_id = payload.get("model") if isinstance(payload, Mapping) else None
        if model_id != decision.model_id or not decision.model_id:
            mismatch = FinalDispatchDecision(
                False, "dispatch_model_mismatch", decision.revision,
                decision.model_id, decision.product_id, decision.tier,
            )
            self._last_decision = mismatch
            raise FinalDispatchDenied("dispatch_model_mismatch", decision=mismatch)
        return decision

    def authorized_service_transport(self, inner: B14ServiceTransport) -> GuardedServiceTransport:
        """Wrap a Worker service-binding transport for the completion path."""
        return GuardedServiceTransport(self, inner)

    def authorized_http_transport(self, inner: Any) -> GuardedHTTPTransport:
        """Wrap a real-httpx transport for the streaming path."""
        return GuardedHTTPTransport(self, inner)


class GuardedServiceTransport:
    """Denies before delegating to the wrapped service-binding transport."""

    def __init__(self, guard: FinalDispatchGuard, inner: Any):
        if not callable(getattr(inner, "post_json", None)):
            raise ValueError("service_transport_binding_required")
        self._guard = guard
        self._inner = inner

    async def post_json(self, url: str, payload: dict[str, Any]) -> tuple[int, bytes]:
        await self._guard.verify_dispatch_payload(payload)
        return await self._inner.post_json(url, payload)


async def _request_payload(request: Any) -> Mapping[str, Any] | None:
    try:
        body = await request.aread()
    except Exception:
        return None
    try:
        payload = json.loads(body or b"{}")
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


class GuardedHTTPTransport(execution_httpx.AsyncBaseTransport):
    """Denies before delegating to the wrapped real-httpx transport.

    Core owns a real ``httpx.AsyncClient``, so this must subclass real
    ``httpx.AsyncBaseTransport`` (same rule as the worker.py streaming bridge);
    it is not part of the B62 ``httpx_compat`` shim family.
    """

    def __init__(self, guard: FinalDispatchGuard, inner: Any):
        if not callable(getattr(inner, "handle_async_request", None)):
            raise ValueError("http_transport_binding_required")
        self._guard = guard
        self._inner = inner

    async def handle_async_request(
        self, request: execution_httpx.Request
    ) -> execution_httpx.Response:
        payload = await _request_payload(request)
        if payload is None:
            raise FinalDispatchDenied(
                "dispatch_model_mismatch",
                decision=self._guard._deny("dispatch_model_mismatch"),
            )
        await self._guard.verify_dispatch_payload(payload)
        return await self._inner.handle_async_request(request)

    async def aclose(self) -> None:
        aclose = getattr(self._inner, "aclose", None)
        if callable(aclose):
            await aclose()
