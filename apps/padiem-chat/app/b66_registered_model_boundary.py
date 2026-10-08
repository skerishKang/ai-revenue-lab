from __future__ import annotations

"""B66 -> B14 model-decision boundary (#3760), source contract only.

This module intentionally registers NO models, chooses NO model priority, and
makes NO provider calls by itself. A future owner-approved, server-trusted B14
resolver and exact-model executor must be explicitly injected. Without BOTH
injections this lane fails closed before any dispatch. No coupling to B62's
Plus/Pro/Max HOLD and no import of Claw's coding AgentProfile.
"""

from dataclasses import dataclass
import re
from typing import Any, Protocol


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_QUOTE_CAPABILITIES = frozenset(("chat",))
_FORBIDDEN_MODEL_IDS = frozenset(("b14/auto",))
_TASK_NAME = "b66.quote.variable_extraction.v1"


class B66ModelRouteError(Exception):
    """Closed-vocabulary internal error; never includes user/provider data."""

    CODES = frozenset((
        "selection_unconfigured",
        "selection_unavailable",
        "selection_ambiguous",
        "model_not_registered",
        "model_not_enabled",
        "model_not_authorized",
        "model_credential_unavailable",
        "model_capability_unavailable",
        "model_identity_invalid",
        "provider_execution_failed",
        "provider_response_invalid",
        "provider_route_mismatch",
    ))

    def __init__(self, code: str) -> None:
        if code not in self.CODES:
            raise ValueError("unrecognized bounded B66 model-route error")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class B66QuoteTaskRequirements:
    """Stable product requirements, never a customer-supplied model hint."""

    task_id: str = _TASK_NAME
    task_type: str = "document"
    required_capabilities: frozenset[str] = _QUOTE_CAPABILITIES
    output_contract: str = "quote.variable-extraction.v1"
    max_attempts: int = 1
    max_retries: int = 0
    allow_external_fallback: bool = False


@dataclass(frozen=True, slots=True)
class B14AuthorizedModelRoute:
    """Attestation returned by a future TRUSTED B14 registered-model authority.

    These flags are not a substitute for live verification by B14. The route
    object MUST NOT be constructed from the HTTP payload or quote text.
    """

    model_id: str
    route_id: str
    owner_policy_id: str
    registered: bool
    enabled: bool
    authorized: bool
    credential_ready: bool
    route_count: int
    capabilities: frozenset[str]


class TrustedB14QuoteModelResolver(Protocol):
    async def resolve_quote_model(
        self, requirements: B66QuoteTaskRequirements
    ) -> B14AuthorizedModelRoute | None: ...


class ExactB14QuoteTextExecutor(Protocol):
    async def execute_quote_text(
        self,
        *,
        route: B14AuthorizedModelRoute,
        messages: list[dict[str, str]],
        additional_system_context: str | None,
        requirements: B66QuoteTaskRequirements,
    ) -> dict[str, Any]: ...


def _safe_id(value: object) -> bool:
    return isinstance(value, str) and bool(_SAFE_ID.fullmatch(value))


def validate_authorized_route(
    selection: object, requirements: B66QuoteTaskRequirements
) -> B14AuthorizedModelRoute:
    """Refuse invalid or unapproved authority answers before model dispatch."""
    if not isinstance(selection, B14AuthorizedModelRoute):
        raise B66ModelRouteError("selection_unavailable")
    if (
        not _safe_id(selection.model_id)
        or not _safe_id(selection.route_id)
        or not _safe_id(selection.owner_policy_id)
        or selection.model_id in _FORBIDDEN_MODEL_IDS
        or selection.model_id.startswith("padiem-profile/")
    ):
        raise B66ModelRouteError("model_identity_invalid")
    if type(selection.route_count) is not int or selection.route_count != 1:
        raise B66ModelRouteError("selection_ambiguous")
    if selection.registered is not True:
        raise B66ModelRouteError("model_not_registered")
    if selection.enabled is not True:
        raise B66ModelRouteError("model_not_enabled")
    if selection.authorized is not True:
        raise B66ModelRouteError("model_not_authorized")
    if selection.credential_ready is not True:
        raise B66ModelRouteError("model_credential_unavailable")
    if (
        not isinstance(selection.capabilities, frozenset)
        or not requirements.required_capabilities.issubset(selection.capabilities)
    ):
        raise B66ModelRouteError("model_capability_unavailable")
    return selection


class B14QuoteExactModelExecutor:
    """Adapter to the existing DispatchAwareB14Client/Core execution path.

    The trusted resolver owns the selection; this executor never selects and
    B14 remains the final registry/credential/provider authority.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    async def execute_quote_text(
        self,
        *,
        route: B14AuthorizedModelRoute,
        messages: list[dict[str, str]],
        additional_system_context: str | None,
        requirements: B66QuoteTaskRequirements,
    ) -> dict[str, Any]:
        if (
            requirements != B66QuoteTaskRequirements()
            or route.model_id in _FORBIDDEN_MODEL_IDS
        ):
            raise B66ModelRouteError("model_identity_invalid")
        return await self._client.complete_registered_quote_model(
            messages,
            model=route.model_id,
            additional_system_context=additional_system_context,
        )


class B66RegisteredModelCompletion:
    """Fail-closed B66 completion facade with explicit-model/no-fallback contract.

    This adapter matches B66QuoteConversationInterpreter's existing .complete
    call. A trusted resolver sees only a constant task requirement, never the
    customer quote, Saved Quote Skill, private prompt or account credentials.

    The executor is owned by B14 and MUST independently validate the registry,
    binding, authorization, route, capabilities and one-shot budget. This facade
    never invents a provider or silently substitutes another route.
    """

    def __init__(
        self,
        *,
        resolver: TrustedB14QuoteModelResolver | None = None,
        executor: ExactB14QuoteTextExecutor | None = None,
    ) -> None:
        self._resolver = resolver
        self._executor = executor

    async def complete(
        self,
        messages: list[dict[str, str]],
        skill: Any | None = None,
        additional_system_context: str | None = None,
        attachments: tuple[Any, ...] = (),
    ) -> dict[str, Any]:
        if self._resolver is None or self._executor is None:
            raise B66ModelRouteError("selection_unconfigured")
        # The B66 quote route and interpreter own bounded text/schema checks.
        # This lane must never receive images, product-tier override or tools.
        if (
            skill is not None
            or attachments != ()
            or not isinstance(messages, list)
            or len(messages) != 1
            or not isinstance(messages[0], dict)
            or set(messages[0]) != {"role", "content"}
            or messages[0].get("role") != "user"
            or not isinstance(messages[0].get("content"), str)
            or not messages[0]["content"].strip()
            or (
                additional_system_context is not None
                and not isinstance(additional_system_context, str)
            )
        ):
            raise B66ModelRouteError("selection_unavailable")

        requirements = B66QuoteTaskRequirements()
        try:
            candidate = await self._resolver.resolve_quote_model(requirements)
        except Exception as exc:
            raise B66ModelRouteError("selection_unavailable") from None
        selected = validate_authorized_route(candidate, requirements)

        # One dispatcher invocation, never a client-side retry/fallback.
        try:
            result = await self._executor.execute_quote_text(
                route=selected,
                messages=[dict(messages[0])],
                additional_system_context=additional_system_context,
                requirements=requirements,
            )
        except Exception:
            raise B66ModelRouteError("provider_execution_failed") from None
        if not isinstance(result, dict) or not isinstance(result.get("answer"), str):
            raise B66ModelRouteError("provider_response_invalid")
        route = result.get("route")
        if not isinstance(route, dict) or (
            route.get("model") != selected.model_id
            or route.get("mode") != "manual"
        ):
            raise B66ModelRouteError("provider_route_mismatch")
        # Output only the already-required B66 extraction field.
        return {"answer": result["answer"]}
