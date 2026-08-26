"""Internal Router-level streaming execution for Business 14.

This module deliberately has no public gateway integration.  It composes an
already-resolved :class:`RouteDecision` with the bounded OpenRouter streaming
primitive introduced by Slice 11.

The safety boundary is simple:

* before the first non-empty content delta, an existing fallback-eligible
  provider error may advance to the next *already resolved* candidate;
* the first non-empty content delta commits the route;
* after commitment, no provider/model fallback is allowed.

The executor never resolves new candidates, never widens capabilities, and
never performs speculative parallel calls.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.pilot.errors import (
    PilotError,
    UpstreamRateLimited,
    UpstreamServerError,
    UpstreamTimeout,
)
from app.pilot.openrouter_stream import (
    OpenRouterStreamEvent,
    OpenRouterStreamUsage,
    stream_openrouter_chat_completions,
)
from app.pilot.router_core import RouteDecision


StreamCall = Callable[..., AsyncIterator[OpenRouterStreamEvent]]


@dataclass(frozen=True, slots=True)
class StreamingRouteCandidate:
    model_id: str
    upstream_model: str
    provider: str
    route_id: str

    def __post_init__(self) -> None:
        for name in ("model_id", "upstream_model", "provider", "route_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")


@dataclass(frozen=True, slots=True)
class RouterStreamEvent:
    """Bounded immutable event for a later gateway/Core streaming adapter."""

    request_id: str
    route_mode: str
    selected_provider: str
    selected_model: str
    selected_upstream_model: str
    selected_route_id: str
    attempt: int
    fallback_used: bool
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    delta_content: str | None = None
    finish_reason: str | None = None
    usage: OpenRouterStreamUsage | None = None
    actual_response_model: str | None = None
    done: bool = False
    committed: bool = False
    error_code: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "request_id",
            "route_mode",
            "selected_provider",
            "selected_model",
            "selected_upstream_model",
            "selected_route_id",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        if isinstance(self.attempt, bool) or not isinstance(self.attempt, int) or self.attempt < 1:
            raise ValueError("attempt must be a positive integer")
        if not isinstance(self.fallback_used, bool):
            raise ValueError("fallback_used must be boolean")
        if not isinstance(self.committed, bool) or not isinstance(self.done, bool):
            raise ValueError("committed and done must be boolean")
        if not isinstance(self.reason_codes, tuple) or not all(
            isinstance(item, str) and item for item in self.reason_codes
        ):
            raise ValueError("reason_codes must be a tuple of non-empty strings")
        for name in ("delta_content", "finish_reason", "actual_response_model", "error_code"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"{name} must be a string or None")
        if self.usage is not None and not isinstance(self.usage, OpenRouterStreamUsage):
            raise ValueError("usage must be OpenRouterStreamUsage or None")
        if self.error_code is not None and not self.done:
            raise ValueError("terminal streaming errors must set done=True")


def _candidate_from_mapping(raw: Mapping[str, Any]) -> StreamingRouteCandidate:
    try:
        return StreamingRouteCandidate(
            model_id=raw["model_id"],
            upstream_model=raw["upstream_model"],
            provider=raw["provider"],
            route_id=raw["route_id"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("RouteDecision contains an invalid fallback candidate") from exc


def _decision_candidates(decision: RouteDecision) -> tuple[StreamingRouteCandidate, ...]:
    primary = StreamingRouteCandidate(
        model_id=decision.selected_model,
        upstream_model=decision.selected_upstream_model,
        provider=decision.selected_provider,
        route_id=decision.selected_route_id,
    )
    fallbacks = tuple(_candidate_from_mapping(item) for item in decision.eligible_fallback)
    # Do not consult the catalog here.  The executor is intentionally incapable
    # of widening the already-resolved candidate set.
    return (primary, *fallbacks)


def _is_precommit_fallback_error(exc: BaseException) -> bool:
    return isinstance(exc, (UpstreamRateLimited, UpstreamTimeout, UpstreamServerError))


def _safe_error_code(exc: BaseException) -> str:
    if isinstance(exc, PilotError):
        return exc.code
    return "stream_execution_error"


def _router_event(
    *,
    decision: RouteDecision,
    candidate: StreamingRouteCandidate,
    attempt: int,
    provider_event: OpenRouterStreamEvent | None = None,
    committed: bool,
    done: bool | None = None,
    error_code: str | None = None,
) -> RouterStreamEvent:
    provider_event = provider_event or OpenRouterStreamEvent()
    return RouterStreamEvent(
        request_id=decision.request_id,
        route_mode=decision.route_mode,
        selected_provider=candidate.provider,
        selected_model=candidate.model_id,
        selected_upstream_model=candidate.upstream_model,
        selected_route_id=candidate.route_id,
        attempt=attempt,
        fallback_used=attempt > 1,
        reason_codes=tuple(decision.reason_codes),
        delta_content=provider_event.delta_content,
        finish_reason=provider_event.finish_reason,
        usage=provider_event.usage,
        actual_response_model=provider_event.model,
        done=provider_event.done if done is None else done,
        committed=committed,
        error_code=error_code,
    )


async def _close_iterator(iterator: Any) -> None:
    closer = getattr(iterator, "aclose", None)
    if callable(closer):
        try:
            await closer()
        except Exception:
            # Cleanup must not hide the already-classified execution result.
            pass


async def stream_routed_chat_completions(
    *,
    decision: RouteDecision,
    messages: Sequence[Mapping[str, str]],
    temperature: float | None,
    max_tokens: int | None,
    stream_call: StreamCall = stream_openrouter_chat_completions,
) -> AsyncIterator[RouterStreamEvent]:
    """Execute one resolved route with bounded pre-content fallback semantics.

    This function does not resolve routes and does not expose a public HTTP
    streaming contract.  It can only use the primary and fallback candidates
    already present in ``decision``.
    """
    if not isinstance(decision, RouteDecision):
        raise ValueError("decision must be RouteDecision")
    if not callable(stream_call):
        raise ValueError("stream_call must be callable")

    candidates = _decision_candidates(decision)
    max_attempts = min(decision.max_attempts, len(candidates))
    if max_attempts < 1:
        raise ValueError("RouteDecision must allow at least one attempt")

    committed = False
    for index, candidate in enumerate(candidates[:max_attempts], start=1):
        iterator = stream_call(
            messages=[dict(message) for message in messages],
            temperature=temperature,
            max_tokens=max_tokens,
            model_id=candidate.model_id,
            upstream_model=candidate.upstream_model,
            provider=candidate.provider,
        )
        buffered: list[OpenRouterStreamEvent] = []
        saw_done = False
        try:
            async for provider_event in iterator:
                visible = bool(provider_event.delta_content)
                if not committed and not visible:
                    buffered.append(provider_event)
                    if provider_event.done:
                        saw_done = True
                        break
                    continue

                if visible and not committed:
                    committed = True
                    for pending in buffered:
                        yield _router_event(
                            decision=decision,
                            candidate=candidate,
                            attempt=index,
                            provider_event=pending,
                            committed=False,
                        )
                    buffered.clear()

                yield _router_event(
                    decision=decision,
                    candidate=candidate,
                    attempt=index,
                    provider_event=provider_event,
                    committed=committed,
                )
                if provider_event.done:
                    saw_done = True
                    return

            if committed:
                # Slice-11 provider primitive normally raises when [DONE] is
                # missing.  Keep a bounded terminal state if an injected
                # compatible iterator ends unexpectedly after commitment.
                if not saw_done:
                    yield _router_event(
                        decision=decision,
                        candidate=candidate,
                        attempt=index,
                        committed=True,
                        done=True,
                        error_code="stream_ended_without_done",
                    )
                return

            # A provider stream that completed without any visible content is
            # not a successful answer and must not silently move to a new model.
            yield _router_event(
                decision=decision,
                candidate=candidate,
                attempt=index,
                committed=False,
                done=True,
                error_code="empty_stream_answer",
            )
            return
        except BaseException as exc:
            if isinstance(exc, (GeneratorExit, KeyboardInterrupt, SystemExit)):
                raise
            if committed:
                yield _router_event(
                    decision=decision,
                    candidate=candidate,
                    attempt=index,
                    committed=True,
                    done=True,
                    error_code=_safe_error_code(exc),
                )
                return

            can_fallback = (
                _is_precommit_fallback_error(exc)
                and decision.fallback_allowed
                and index < max_attempts
            )
            if can_fallback:
                continue

            yield _router_event(
                decision=decision,
                candidate=candidate,
                attempt=index,
                committed=False,
                done=True,
                error_code=_safe_error_code(exc),
            )
            return
        finally:
            await _close_iterator(iterator)
