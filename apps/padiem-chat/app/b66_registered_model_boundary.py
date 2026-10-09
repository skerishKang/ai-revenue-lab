from __future__ import annotations

"""B66 -> B14 model-decision boundary (#3760), source contract only.

This module intentionally registers NO models, chooses NO model priority, and
makes NO provider calls by itself. A future owner-approved, server-trusted B14
resolver and exact-model executor must be explicitly injected. Without BOTH
injections this lane fails closed before any dispatch. No coupling to B62's
Plus/Pro/Max HOLD and no import of Claw's coding AgentProfile.
"""

from dataclasses import dataclass, replace
import re
from typing import Any, Awaitable, Callable, Protocol

from .b14_client import ChatRuntimeError
from .b66_reasoning_level import (
    DEFAULT_REASONING_LEVEL,
    reasoning_parameter_for_request,
    reasoning_transport_available,
    verified_reasoning_levels_for_model,
)


_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}\Z")
_QUOTE_CAPABILITIES = frozenset(("chat",))
_FORBIDDEN_MODEL_IDS = frozenset(("b14/auto",))
_TASK_NAME = "b66.quote.variable_extraction.v1"


class B66ModelRouteError(Exception):
    """Closed-vocabulary internal error; never includes user/provider data."""

    CODES = frozenset((
        "runtime_unavailable",
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
    """Stable quote task, with an explicitly selected exact B14 model ID."""

    task_id: str = _TASK_NAME
    task_type: str = "document"
    required_capabilities: frozenset[str] = _QUOTE_CAPABILITIES
    output_contract: str = "quote.variable-extraction.v1"
    max_attempts: int = 1
    max_retries: int = 0
    allow_external_fallback: bool = False
    selected_model_id: str | None = None


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
        model_parameters: dict[str, Any] | None = None,
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
    if requirements.selected_model_id is not None and selection.model_id != requirements.selected_model_id:
        raise B66ModelRouteError("model_not_authorized")
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

    @property
    def supports_native_parameters(self) -> bool:
        """Whether the shared Core transport can carry native parameters.

        The Core/B14 owner sets this when the validated opt-in contract
        (#3977) is present. Absent or False means "cannot carry", so B66
        refuses an explicit level instead of dropping it.
        """
        return bool(getattr(self._client, "supports_native_model_parameters", False))

    def ensure_runtime_available(self) -> None:
        self._client.ensure_registered_quote_runtime_available()

    async def execute_quote_text(
        self,
        *,
        route: B14AuthorizedModelRoute,
        messages: list[dict[str, str]],
        additional_system_context: str | None,
        requirements: B66QuoteTaskRequirements,
        model_parameters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if (
            replace(requirements, selected_model_id=None) != B66QuoteTaskRequirements()
            or route.model_id in _FORBIDDEN_MODEL_IDS
            or route.model_id != requirements.selected_model_id
        ):
            raise B66ModelRouteError("model_identity_invalid")
        if model_parameters is None:
            return await self._client.complete_registered_quote_model(
                messages,
                model=route.model_id,
                additional_system_context=additional_system_context,
            )
        # Validated B14-native optional parameters only (#3906). The shared Core
        # owns this transport; if the installed Core/client cannot carry them,
        # fail closed BEFORE the request instead of dropping the customer's
        # explicit choice.
        if not self.supports_native_parameters:
            raise B66ModelRouteError("model_capability_unavailable")
        return await self._client.complete_registered_quote_model(
            messages,
            model=route.model_id,
            additional_system_context=additional_system_context,
            model_parameters=dict(model_parameters),
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
        refund_pre_dispatch: Callable[[], Awaitable[bool]] | None = None,
    ) -> None:
        self._resolver = resolver
        self._executor = executor
        self._refund_pre_dispatch = refund_pre_dispatch

    async def _refund_before_dispatch(self) -> None:
        if self._refund_pre_dispatch is not None:
            try:
                await self._refund_pre_dispatch()
            except Exception:
                pass  # A refund failure must not hide the bounded route error.

    async def _reasoning_parameters(
        self, model_id: str, reasoning_level: str | None
    ) -> dict[str, Any] | None:
        """Validate the customer's level into validated B14-native arguments.

        ``None`` (omitted) and ``default`` both mean "provider default" and
        return ``None`` so that NOTHING new reaches the executor or the wire.
        An unsupported or unverifiable value fails closed with a refund and no
        dispatch, rather than being ignored, downgraded, or applied to another
        model.
        """
        if reasoning_level is None or reasoning_level == DEFAULT_REASONING_LEVEL:
            return None
        if not isinstance(reasoning_level, str):
            await self._refund_before_dispatch()
            raise B66ModelRouteError("model_capability_unavailable")
        if reasoning_level not in verified_reasoning_levels_for_model(model_id):
            # Well-formed value, but not proven for this exact served model ID.
            await self._refund_before_dispatch()
            raise B66ModelRouteError("model_capability_unavailable")
        try:
            parameters = reasoning_parameter_for_request(model_id, reasoning_level)
        except ValueError:
            await self._refund_before_dispatch()
            raise B66ModelRouteError("model_capability_unavailable") from None
        if not parameters:
            await self._refund_before_dispatch()
            raise B66ModelRouteError("model_capability_unavailable")
        # The shared Core transport is B14/#3977 owned and opt-in. Refusing
        # here keeps the promise "an explicit choice is either honoured or
        # refused", instead of silently answering with the provider default.
        if not reasoning_transport_available(
            model_id, transport_supported=self._native_transport_supported()
        ):
            await self._refund_before_dispatch()
            raise B66ModelRouteError("model_capability_unavailable")
        return parameters

    def _native_transport_supported(self) -> bool:
        """Capability declared by the injected Core-owning executor."""
        return getattr(self._executor, "supports_native_parameters", False) is True

    async def complete(
        self,
        messages: list[dict[str, str]],
        skill: Any | None = None,
        additional_system_context: str | None = None,
        attachments: tuple[Any, ...] = (),
        model_id: str | None = None,
        reasoning_level: str | None = None,
    ) -> dict[str, Any]:
        if self._resolver is None or self._executor is None:
            await self._refund_before_dispatch()
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
            await self._refund_before_dispatch()
            raise B66ModelRouteError("selection_unavailable")

        if not _safe_id(model_id) or model_id in _FORBIDDEN_MODEL_IDS or model_id.startswith("padiem-profile/"):
            await self._refund_before_dispatch()
            raise B66ModelRouteError("selection_unconfigured")
        # #3906: an explicit reasoning level is normalized HERE, at the real
        # adapter boundary, and never forwarded as an unvalidated keyword.
        # `default` and an absent value mean provider-native omission, so the
        # request below is byte-identical to the pre-#3906 call.
        native_parameters = await self._reasoning_parameters(model_id, reasoning_level)
        requirements = replace(B66QuoteTaskRequirements(), selected_model_id=model_id)
        try:
            # The concrete Worker executor checks mock/live/binding readiness
            # before registry reads. Pure trusted offline executors need no I/O.
            runtime_check = getattr(self._executor, "ensure_runtime_available", None)
            if callable(runtime_check):
                runtime_check()
            candidate = await self._resolver.resolve_quote_model(requirements)
            selected = validate_authorized_route(candidate, requirements)
        except Exception as exc:
            # A denied local policy/readiness decision did not dispatch B14.
            # Preserve B62/Claw usage accounting without charging denied B66.
            await self._refund_before_dispatch()
            if isinstance(exc, ChatRuntimeError):
                raise B66ModelRouteError("runtime_unavailable") from None
            if isinstance(exc, B66ModelRouteError):
                raise
            raise B66ModelRouteError("selection_unavailable") from None

        # One dispatcher invocation, never a client-side retry/fallback.
        try:
            result = await self._executor.execute_quote_text(
                route=selected,
                messages=[dict(messages[0])],
                additional_system_context=additional_system_context,
                requirements=requirements,
                model_parameters=native_parameters,
            )
        except ChatRuntimeError:
            # Keep the existing bounded provider timeout/server/shape class.
            # The HTTP route projects only its closed diagnostic vocabulary.
            raise
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
