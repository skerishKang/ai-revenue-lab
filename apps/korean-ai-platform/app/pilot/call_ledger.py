"""Durable per-call execution ledger for the Business 14 gateway (#5318).

B14 is the only layer that sees the *actual physical provider attempts*: a
fallback that failed on one supplier and succeeded on the next exists nowhere
else in the platform. Two surfaces already carry part of that truth and neither
is durable:

* ``stack_telemetry`` ships OTLP events that are deliberately
  provider-identity-blind, and its tests forbid adding provider, model, token
  or cost fields to those events;
* ``attempt_evidence`` is a response payload whose key set is pinned by
  ``tests/test_upstream_retry.py`` and is discarded once the response is sent.

So the ledger is a third surface with its own rules, built from the values the
gateway already measured. It records no number that was not observed, and it
never estimates what the provider did not report.

Two distinctions the contract exists to preserve:

* **measured vs missing**, not missing vs zero. A provider that sent no usage
  is recorded as ``missing`` with ``NULL`` token columns. A stored zero would
  read later as "this call cost nothing".
* **observed vs declared**. The physical attempt, provider, model and tokens are
  observed by B14. The originating product and its correlation id arrive in a
  caller header and stay labelled ``caller_declared`` — B14 does not upgrade a
  claim it received into a fact it measured.

Cost is a catalog price snapshot applied to measured tokens. It is an estimate
and is named as one; this ledger is not a commercial ledger and performs no
billing action. Prompts, responses, headers, cookies, IP addresses and provider
credentials are outside the schema on purpose. The only thing a row says about
a credential is which side of that boundary it came from: ``pool`` or ``user``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any

# Token evidence states. ``estimated`` is reserved on purpose: nothing here
# infers a token count the provider did not send.
TOKEN_MEASURED = "measured"
TOKEN_MISSING = "missing"

# Cost basis reuses the gateway's existing vocabulary, so one ledger and the
# response metadata never disagree about why a cost is unknown.
COST_CONFIGURED = "configured_snapshot"
COST_KNOWN_FREE = "known_free"
COST_UNKNOWN = "unknown"

# Latency evidence follows ``routing_evidence.LatencyEvidenceSource``: a
# configured class must never be stored as a measurement.
LATENCY_MEASURED = "measured"
LATENCY_UNKNOWN = "unknown"

ORIGIN_OBSERVED = "b14_observed"
ORIGIN_DECLARED = "caller_declared"
ORIGIN_UNKNOWN = "unknown"

OUTCOME_SUCCESS = "success"
OUTCOME_ERROR = "error"
OUTCOME_ABORTED = "aborted"

#: The wire families a B14 attempt can name. The set is closed and matched by
#: the storage CHECK constraint, so a new family needs a migration, not a label:
#: ``native`` is the provider's own request shape (Google's
#: ``models/{model}:streamGenerateContent`` tool wire today) as opposed to any
#: OpenAI-compatible ``chat/completions`` endpoint.
#: Whose credential the call spent. ``pool`` is a platform-owned Provider key
#: selected from the roster; ``user`` is a key that arrived with this request
#: only. The pair is a category, never a reference to the key itself, and it is
#: what separates platform consumption from a customer spending their own
#: account (#5824 PR-3a).
CREDENTIAL_POOL = "pool"
CREDENTIAL_USER = "user"

_PROTOCOLS = frozenset({"responses", "messages", "chat/completions", "native", "unknown"})
_PRODUCTS = frozenset({"chat", "claw", "b66", "engine", "api", "unknown"})

# Identifiers are bounded technical ids, never prose. ``subject_ref`` and
# ``tenant_ref`` are opaque references the calling product already holds; B14
# stores them as delivered and never resolves them to a person.
_ID_RE = re.compile(r"^[A-Za-z0-9._:@/-]{1,128}$")
# Identity-adjacent references get a stricter grammar than technical ids: an
# opaque member id is fine, an email address is not. Without this, a caller
# could move a person's address into a usage ledger row that the read API
# returns, and the row would outlive the conversation it came from.
_REF_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,128}$")
_MAX_ID = 128
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}$")
_MAX_TEXT = 256

LEDGER_ID_PREFIX = "b14call_"
_LEDGER_PREFIX = LEDGER_ID_PREFIX  # historical private name


class CallLedgerError(ValueError):
    """A ledger record that would store an unverifiable or oversized value."""


def new_log_id() -> str:
    """Mint one immutable ledger id. It is generated once and never rewritten."""
    import uuid

    return f"{_LEDGER_PREFIX}{uuid.uuid4().hex[:20]}"


def utc_now_iso() -> str:
    """Second-precision UTC stamp, the format every stored timestamp uses."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_id(name: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CallLedgerError(f"{name} must be a string")
    text = value.strip()
    if not text:
        return None
    if len(text) > _MAX_ID or not _ID_RE.fullmatch(text):
        # A value that is not a bounded technical id is dropped rather than
        # truncated: a half-stored identifier would silently join the wrong
        # request during a later lookup.
        raise CallLedgerError(f"{name} is not a bounded safe identifier")
    return text


def _clean_ref(name: str, value: Any) -> str | None:
    """Clean an identity-adjacent reference: opaque id only, never an address."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise CallLedgerError(f"{name} must be a string")
    text = value.strip()
    if not text:
        return None
    if _EMAIL_RE.fullmatch(text):
        raise CallLedgerError(f"{name} must not be an email address")
    if not _REF_RE.fullmatch(text):
        raise CallLedgerError(f"{name} is not a bounded opaque reference")
    return text


def _clean_text(name: str, value: Any, limit: int = _MAX_TEXT) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CallLedgerError(f"{name} must be a string")
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > limit:
        raise CallLedgerError(f"{name} exceeds the stored bound")
    return text


def _non_negative_int(name: str, value: Any, *, allow_none: bool = True) -> int | None:
    if value is None:
        if allow_none:
            return None
        raise CallLedgerError(f"{name} is required")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CallLedgerError(f"{name} must be a non-negative integer or None")
    return value


def _positive_int(name: str, value: Any) -> int:
    return _non_negative_int(name, value, allow_none=False) or 0  # type: ignore[return-value]


def _http_status(value: Any) -> int | None:
    status = _non_negative_int("http_status", value)
    if status is not None and not 100 <= status <= 599:
        raise CallLedgerError("http_status must be a valid HTTP status")
    return status


def _money(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CallLedgerError("cost estimate must be a number or None")
    number = float(value)
    if number < 0:
        raise CallLedgerError("cost estimate must not be negative")
    return round(number, 6)


def _timestamp(name: str, value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CallLedgerError(f"{name} must be an ISO-8601 UTC string")
    text = value.strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CallLedgerError(f"{name} must be an ISO-8601 UTC string") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CallLedgerError(f"{name} must carry a timezone")
    return text


def token_evidence(usage: Any) -> tuple[int | None, int | None, int | None, int | None, str]:
    """Return one attempt's (prompt, completion, total, reasoning, source).

    A provider that reports nothing yields ``None`` values with source
    ``missing``. A partial report keeps its own gaps as ``None`` instead of
    being completed by arithmetic, because a derived total would look like an
    observed one in every later aggregate.
    """
    data = usage if isinstance(usage, dict) else {}
    prompt = _non_negative_int("prompt_tokens", data.get("prompt_tokens"))
    completion = _non_negative_int("completion_tokens", data.get("completion_tokens"))
    total = _non_negative_int("total_tokens", data.get("total_tokens"))
    details = data.get("completion_tokens_details")
    reasoning = (
        _non_negative_int("reasoning_tokens", details.get("reasoning_tokens"))
        if isinstance(details, dict) else None
    )
    if prompt is None and completion is None and total is None:
        return None, None, None, None, TOKEN_MISSING
    return prompt, completion, total, reasoning, TOKEN_MEASURED


def cost_estimate(
    model_id: str | None, prompt_tokens: int | None, completion_tokens: int | None,
) -> tuple[float | None, float | None, str]:
    """Apply the configured catalog price snapshot to measured tokens.

    Unknown prices and absent usage both yield ``None`` with basis ``unknown``;
    a known-zero price yields ``0.0`` with basis ``known_free``. The difference
    between the two is the whole point of keeping the basis column.
    """
    if model_id is None or prompt_tokens is None or completion_tokens is None:
        return None, None, COST_UNKNOWN
    from app.pilot.catalog import get_catalog_by_id

    model = get_catalog_by_id(model_id)
    if model is None or not model.price_is_known:
        return None, None, COST_UNKNOWN
    usd = model.estimate_cost_usd(prompt_tokens, completion_tokens)
    krw = model.estimate_cost_krw(prompt_tokens, completion_tokens)
    if usd is None:
        return None, None, COST_UNKNOWN
    return usd, krw, COST_KNOWN_FREE if usd == 0.0 else COST_CONFIGURED


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """One physical provider attempt, successful or not.

    A failed attempt is a row of its own. Fallback must stay visible after the
    fact instead of being overwritten by the attempt that eventually answered.
    """

    log_id: str
    attempt_index: int
    provider: str | None = None
    model_id: str | None = None
    upstream_model: str | None = None
    route_id: str | None = None
    outcome: str = OUTCOME_SUCCESS
    error_code: str | None = None
    retry_index: int = 0
    actual_response_model: str | None = None
    finish_reason: str | None = None
    provider_request_id: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_ms: int | None = None
    latency_source: str = LATENCY_UNKNOWN
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    token_source: str = TOKEN_MISSING
    estimated_usd: float | None = None
    estimated_krw: float | None = None
    cost_basis: str = COST_UNKNOWN
    endpoint: str | None = None
    protocol: str = "unknown"
    #: Whether this candidate was actually sent to a provider. A candidate the
    #: gateway skipped (for example a route that cannot serve a declared tool)
    #: is visible evidence, but it is not a provider call and must never be
    #: counted as one in a latency or cost aggregate.
    dispatched: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "log_id", _clean_id("log_id", self.log_id) or "")
        if not self.log_id.startswith(_LEDGER_PREFIX):
            raise CallLedgerError("attempt log_id must be a ledger id")
        index = _non_negative_int("attempt_index", self.attempt_index, allow_none=False)
        if index is None or index > 32:
            raise CallLedgerError("attempt_index is out of range")
        if self.outcome not in {OUTCOME_SUCCESS, OUTCOME_ERROR, OUTCOME_ABORTED}:
            raise CallLedgerError("attempt outcome is not a known outcome")
        if self.protocol not in _PROTOCOLS:
            raise CallLedgerError("attempt protocol is not a known protocol")
        if self.latency_source not in {LATENCY_MEASURED, LATENCY_UNKNOWN}:
            raise CallLedgerError("attempt latency source is not a known state")
        if self.token_source not in {TOKEN_MEASURED, TOKEN_MISSING}:
            raise CallLedgerError("attempt token source is not a known state")
        if self.cost_basis not in {COST_CONFIGURED, COST_KNOWN_FREE, COST_UNKNOWN}:
            raise CallLedgerError("attempt cost basis is not a known state")
        # A measured token row must carry at least one real number, and a
        # missing row must carry none. That is what stops an inferred zero from
        # entering the ledger as evidence.
        observed = (self.prompt_tokens, self.completion_tokens, self.total_tokens)
        if self.token_source == TOKEN_MEASURED and all(value is None for value in observed):
            raise CallLedgerError("measured tokens require a reported value")
        if self.token_source == TOKEN_MISSING and any(value is not None for value in observed):
            raise CallLedgerError("a reported token cannot be recorded as missing")
        if self.latency_source == LATENCY_UNKNOWN and self.elapsed_ms is not None:
            raise CallLedgerError("an unmeasured latency cannot store a duration")
        if not self.dispatched:
            # A skipped candidate is evidence of a routing decision, not of a
            # provider call. It can carry no duration, no usage and no cost,
            # otherwise a later aggregate would read it as consumption.
            if self.elapsed_ms is not None or self.token_source != TOKEN_MISSING:
                raise CallLedgerError("an undispatched attempt cannot carry a call result")
            if self.cost_basis != COST_UNKNOWN:
                raise CallLedgerError("an undispatched attempt cannot carry a cost basis")
            if self.outcome == OUTCOME_SUCCESS:
                raise CallLedgerError("an undispatched attempt cannot have succeeded")

        object.__setattr__(self, "provider", _clean_text("provider", self.provider, 64))
        object.__setattr__(self, "model_id", _clean_id("model_id", self.model_id))
        object.__setattr__(self, "upstream_model", _clean_id("upstream_model", self.upstream_model))
        object.__setattr__(self, "route_id", _clean_id("route_id", self.route_id))
        object.__setattr__(self, "error_code", _clean_text("error_code", self.error_code, 64))
        object.__setattr__(self, "actual_response_model", _clean_id("actual_response_model", self.actual_response_model))
        object.__setattr__(self, "finish_reason", _clean_text("finish_reason", self.finish_reason, 48))
        object.__setattr__(self, "provider_request_id", _clean_id("provider_request_id", self.provider_request_id))
        object.__setattr__(self, "endpoint", _clean_text("endpoint", self.endpoint, 96))
        object.__setattr__(self, "started_at", _timestamp("started_at", self.started_at))
        object.__setattr__(self, "finished_at", _timestamp("finished_at", self.finished_at))
        object.__setattr__(self, "elapsed_ms", _non_negative_int("elapsed_ms", self.elapsed_ms))
        object.__setattr__(self, "prompt_tokens", _non_negative_int("prompt_tokens", self.prompt_tokens))
        object.__setattr__(self, "completion_tokens", _non_negative_int("completion_tokens", self.completion_tokens))
        object.__setattr__(self, "total_tokens", _non_negative_int("total_tokens", self.total_tokens))
        object.__setattr__(self, "reasoning_tokens", _non_negative_int("reasoning_tokens", self.reasoning_tokens))
        object.__setattr__(self, "estimated_usd", _money(self.estimated_usd))
        object.__setattr__(self, "estimated_krw", _money(self.estimated_krw))
        object.__setattr__(self, "retry_index", _non_negative_int("retry_index", self.retry_index) or 0)

    @property
    def consumed_tokens(self) -> bool:
        """Whether this attempt is evidence of model consumption."""
        return self.outcome == OUTCOME_SUCCESS and self.token_source == TOKEN_MEASURED

    def to_row(self) -> dict[str, Any]:
        return {
            "log_id": self.log_id,
            "attempt_index": self.attempt_index,
            "provider": self.provider,
            "model_id": self.model_id,
            "upstream_model": self.upstream_model,
            "route_id": self.route_id,
            "outcome": self.outcome,
            "error_code": self.error_code,
            "retry_index": self.retry_index,
            "actual_response_model": self.actual_response_model,
            "finish_reason": self.finish_reason,
            "provider_request_id": self.provider_request_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_ms": self.elapsed_ms,
            "latency_source": self.latency_source,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "token_source": self.token_source,
            "estimated_usd": self.estimated_usd,
            "estimated_krw": self.estimated_krw,
            "cost_basis": self.cost_basis,
            "endpoint": self.endpoint,
            "protocol": self.protocol,
            "dispatched": 1 if self.dispatched else 0,
        }


@dataclass(frozen=True, slots=True)
class CallRecord:
    """One logical request: what the caller asked for and what actually answered.

    ``requested_model_id`` is the caller's selection. ``selected_model_id`` and
    ``actual_response_model`` are what B14 dispatched and what the provider
    reported back. Under fallback those differ, and the dashboard has to show
    the difference rather than one merged "model" field.
    """

    log_id: str
    request_id: str
    endpoint: str
    product: str = "unknown"
    origin_source: str = ORIGIN_UNKNOWN
    origin_request_id: str | None = None
    subject_ref: str | None = None
    tenant_ref: str | None = None
    membership_tier: str | None = None
    client_app: str | None = None
    client_version: str | None = None
    session_ref: str | None = None
    requested_model_id: str | None = None
    selected_model_id: str | None = None
    selected_provider: str | None = None
    selected_upstream_model: str | None = None
    selected_route_id: str | None = None
    actual_response_model: str | None = None
    route_mode: str | None = None
    streaming: bool = False
    protocol: str = "unknown"
    outcome: str = OUTCOME_SUCCESS
    http_status: int | None = None
    error_code: str | None = None
    finish_reason: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    elapsed_ms: int | None = None
    latency_source: str = LATENCY_UNKNOWN
    ttft_ms: int | None = None
    attempt_count: int = 0
    fallback_used: bool = False
    fallback_depth: int = 0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    token_source: str = TOKEN_MISSING
    estimated_usd: float | None = None
    estimated_krw: float | None = None
    cost_basis: str = COST_UNKNOWN
    currency: str = "USD"
    credential_source: str = CREDENTIAL_POOL
    attempts: tuple[AttemptRecord, ...] = ()

    def __post_init__(self) -> None:
        log_id = _clean_id("log_id", self.log_id)
        if log_id is None or not log_id.startswith(_LEDGER_PREFIX):
            raise CallLedgerError("log_id must be a ledger id")
        object.__setattr__(self, "log_id", log_id)
        object.__setattr__(self, "request_id", _clean_id("request_id", self.request_id) or "")
        if not self.request_id:
            raise CallLedgerError("request_id is required")
        if self.product not in _PRODUCTS:
            raise CallLedgerError("originating product is not a known product")
        if self.origin_source not in {ORIGIN_OBSERVED, ORIGIN_DECLARED, ORIGIN_UNKNOWN}:
            raise CallLedgerError("origin source is not a known state")
        # A product name the caller declared is only ever a declaration. The
        # record keeps that label even when the value looks plausible.
        if self.product != "unknown" and self.origin_source == ORIGIN_UNKNOWN:
            object.__setattr__(self, "origin_source", ORIGIN_DECLARED)
        if self.protocol not in _PROTOCOLS:
            raise CallLedgerError("call protocol is not a known protocol")
        if self.outcome not in {OUTCOME_SUCCESS, OUTCOME_ERROR, OUTCOME_ABORTED}:
            raise CallLedgerError("call outcome is not a known outcome")
        if self.latency_source not in {LATENCY_MEASURED, LATENCY_UNKNOWN}:
            raise CallLedgerError("call latency source is not a known state")
        if self.token_source not in {TOKEN_MEASURED, TOKEN_MISSING}:
            raise CallLedgerError("call token source is not a known state")
        if self.cost_basis not in {COST_CONFIGURED, COST_KNOWN_FREE, COST_UNKNOWN}:
            raise CallLedgerError("call cost basis is not a known state")
        if self.credential_source not in {CREDENTIAL_POOL, CREDENTIAL_USER}:
            raise CallLedgerError("call credential source is not a known state")

        observed = (self.prompt_tokens, self.completion_tokens, self.total_tokens)
        if self.token_source == TOKEN_MEASURED and all(value is None for value in observed):
            raise CallLedgerError("measured tokens require a reported value")
        if self.token_source == TOKEN_MISSING and any(value is not None for value in observed):
            raise CallLedgerError("a reported token cannot be recorded as missing")
        if self.latency_source == LATENCY_UNKNOWN and self.elapsed_ms is not None:
            raise CallLedgerError("an unmeasured latency cannot store a duration")
        if self.reasoning_tokens is not None and self.token_source != TOKEN_MEASURED:
            raise CallLedgerError("reasoning tokens require measured token evidence")

        attempts = tuple(self.attempts or ())
        if any(not isinstance(a, AttemptRecord) for a in attempts):
            raise CallLedgerError("attempts must contain AttemptRecord items")
        indexes = [a.attempt_index for a in attempts]
        if len(set(indexes)) != len(indexes):
            raise CallLedgerError("attempts carry a duplicate attempt_index")
        if any(a.log_id != self.log_id for a in attempts):
            raise CallLedgerError("attempts must belong to this ledger id")
        if attempts and len(attempts) != self.attempt_count:
            # The parent's attempt count and the child rows are the same fact
            # twice. A mismatch would make an aggregate disagree with the list.
            raise CallLedgerError("attempt_count must match the attempt rows")
        object.__setattr__(self, "attempts", attempts)

        object.__setattr__(self, "endpoint", _clean_text("endpoint", self.endpoint, 96))
        object.__setattr__(self, "origin_request_id", _clean_id("origin_request_id", self.origin_request_id))
        object.__setattr__(self, "subject_ref", _clean_ref("subject_ref", self.subject_ref))
        object.__setattr__(self, "tenant_ref", _clean_ref("tenant_ref", self.tenant_ref))
        object.__setattr__(self, "membership_tier", _clean_text("membership_tier", self.membership_tier, 32))
        object.__setattr__(self, "client_app", _clean_text("client_app", self.client_app, 64))
        object.__setattr__(self, "client_version", _clean_text("client_version", self.client_version, 48))
        object.__setattr__(self, "session_ref", _clean_ref("session_ref", self.session_ref))
        object.__setattr__(self, "requested_model_id", _clean_id("requested_model_id", self.requested_model_id))
        object.__setattr__(self, "selected_model_id", _clean_id("selected_model_id", self.selected_model_id))
        object.__setattr__(self, "selected_provider", _clean_text("selected_provider", self.selected_provider, 64))
        object.__setattr__(self, "selected_upstream_model", _clean_id("selected_upstream_model", self.selected_upstream_model))
        object.__setattr__(self, "selected_route_id", _clean_id("selected_route_id", self.selected_route_id))
        object.__setattr__(self, "actual_response_model", _clean_id("actual_response_model", self.actual_response_model))
        object.__setattr__(self, "route_mode", _clean_text("route_mode", self.route_mode, 16))
        object.__setattr__(self, "error_code", _clean_text("error_code", self.error_code, 64))
        object.__setattr__(self, "finish_reason", _clean_text("finish_reason", self.finish_reason, 48))
        object.__setattr__(self, "started_at", _timestamp("started_at", self.started_at))
        object.__setattr__(self, "finished_at", _timestamp("finished_at", self.finished_at))
        object.__setattr__(self, "elapsed_ms", _non_negative_int("elapsed_ms", self.elapsed_ms))
        object.__setattr__(self, "ttft_ms", _non_negative_int("ttft_ms", self.ttft_ms))
        object.__setattr__(self, "http_status", _http_status(self.http_status))
        object.__setattr__(self, "attempt_count", _non_negative_int("attempt_count", self.attempt_count) or 0)
        object.__setattr__(self, "fallback_depth", _non_negative_int("fallback_depth", self.fallback_depth) or 0)
        object.__setattr__(self, "prompt_tokens", _non_negative_int("prompt_tokens", self.prompt_tokens))
        object.__setattr__(self, "completion_tokens", _non_negative_int("completion_tokens", self.completion_tokens))
        object.__setattr__(self, "total_tokens", _non_negative_int("total_tokens", self.total_tokens))
        object.__setattr__(self, "reasoning_tokens", _non_negative_int("reasoning_tokens", self.reasoning_tokens))
        object.__setattr__(self, "estimated_usd", _money(self.estimated_usd))
        object.__setattr__(self, "estimated_krw", _money(self.estimated_krw))
        object.__setattr__(self, "currency", _clean_text("currency", self.currency, 8) or "USD")

    @property
    def consumed_tokens(self) -> bool:
        return self.token_source == TOKEN_MEASURED

    def to_row(self) -> dict[str, Any]:
        return {
            "log_id": self.log_id,
            "request_id": self.request_id,
            "endpoint": self.endpoint,
            "product": self.product,
            "origin_source": self.origin_source,
            "origin_request_id": self.origin_request_id,
            "subject_ref": self.subject_ref,
            "tenant_ref": self.tenant_ref,
            "membership_tier": self.membership_tier,
            "client_app": self.client_app,
            "client_version": self.client_version,
            "session_ref": self.session_ref,
            "requested_model_id": self.requested_model_id,
            "selected_model_id": self.selected_model_id,
            "selected_provider": self.selected_provider,
            "selected_upstream_model": self.selected_upstream_model,
            "selected_route_id": self.selected_route_id,
            "actual_response_model": self.actual_response_model,
            "route_mode": self.route_mode,
            "streaming": 1 if self.streaming else 0,
            "protocol": self.protocol,
            "outcome": self.outcome,
            "http_status": self.http_status,
            "error_code": self.error_code,
            "finish_reason": self.finish_reason,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_ms": self.elapsed_ms,
            "latency_source": self.latency_source,
            "ttft_ms": self.ttft_ms,
            "attempt_count": self.attempt_count,
            "fallback_used": 1 if self.fallback_used else 0,
            "fallback_depth": self.fallback_depth,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "token_source": self.token_source,
            "estimated_usd": self.estimated_usd,
            "estimated_krw": self.estimated_krw,
            "cost_basis": self.cost_basis,
            "currency": self.currency,
            "credential_source": self.credential_source,
        }

    def public_dict(self) -> dict[str, Any]:
        """The admin read shape: stored facts plus the semantics of their gaps."""
        row = self.to_row()
        row["streaming"] = bool(row["streaming"])
        row["fallback_used"] = bool(row["fallback_used"])
        row["attempts"] = [attempt.to_row() for attempt in self.attempts]
        for attempt in row["attempts"]:
            attempt["outcome_observed"] = attempt["outcome"]
        row["evidence"] = {
            "tokens": self.token_source,
            "latency": self.latency_source,
            "cost": self.cost_basis,
            "origin": self.origin_source,
            "model_answer": "actual_response_model" if self.actual_response_model else None,
        }
        return row


def origin_from_headers(headers: Any) -> dict[str, str | None]:
    """Read the declared origin from the existing allowlisted request headers.

    B14 already trusts only technical correlation headers. Nothing here reads a
    cookie, an authorization value or a raw user agent into the ledger.
    """
    def get(name: str) -> str | None:
        try:
            value = headers.get(name) if headers is not None else None
        except Exception:
            return None
        return value if isinstance(value, str) else None

    product = (get("x-padiem-product") or "").strip().lower() or None
    return {
        "product": product if product in _PRODUCTS else "unknown",
        "origin_request_id": get("x-request-id"),
        "subject_ref": get("x-padiem-subject-ref"),
        "tenant_ref": get("x-padiem-tenant-ref"),
        "membership_tier": get("x-padiem-tier"),
        "client_app": get("x-padiem-client-app"),
        "client_version": get("x-padiem-client-version"),
        "session_ref": get("x-padiem-session-ref"),
    }


@dataclass
class LedgerDraft:
    """The accumulator a request fills while its physical attempts happen.

    A gateway lane records each attempt as it occurs rather than reconstructing
    the walk at the end, because a fallback chain that succeeded tells you
    nothing about the attempt that failed unless the failed one was written
    down when it happened.
    """

    log_id: str
    request_id: str
    endpoint: str
    protocol: str
    streaming: bool
    requested_model_id: str | None
    started_at: str
    origin: dict[str, str | None] = field(default_factory=dict)
    attempts: list[AttemptRecord] = field(default_factory=list)
    #: First visible output, measured on the streaming lane. It belongs to the
    #: logical request: several attempts may have run before one of them
    #: produced the token the caller actually saw.
    ttft_ms: int | None = None

    @property
    def attempt_count(self) -> int:
        return len(self.attempts)

    def record_attempt(
        self, *, provider: str | None, model_id: str | None,
        upstream_model: str | None = None, route_id: str | None = None,
        outcome: str = OUTCOME_SUCCESS, error_code: str | None = None,
        retry_index: int = 0, elapsed_ms: int | None = None,
        usage: Any = None, actual_response_model: str | None = None,
        finish_reason: str | None = None, provider_request_id: str | None = None,
        dispatched: bool = True, protocol: str | None = None,
    ) -> AttemptRecord:
        prompt, completion, total, reasoning, token_source = token_evidence(usage)
        estimated_usd, estimated_krw, basis = cost_estimate(
            actual_response_model or model_id, prompt, completion
        )
        attempt = AttemptRecord(
            log_id=self.log_id, attempt_index=self.attempt_count,
            provider=provider, model_id=model_id, upstream_model=upstream_model,
            route_id=route_id, outcome=outcome, error_code=error_code,
            retry_index=retry_index, actual_response_model=actual_response_model,
            finish_reason=finish_reason, provider_request_id=provider_request_id,
            started_at=None, finished_at=utc_now_iso(),
            elapsed_ms=elapsed_ms,
            latency_source=LATENCY_MEASURED if elapsed_ms is not None else LATENCY_UNKNOWN,
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=total,
            reasoning_tokens=reasoning, token_source=token_source,
            estimated_usd=estimated_usd, estimated_krw=estimated_krw,
            cost_basis=basis, endpoint=self.endpoint,
            protocol=protocol or self.protocol,
            dispatched=dispatched,
        )
        self.attempts.append(attempt)
        return attempt

    def finish(
        self, *, outcome: str, http_status: int | None = None,
        error_code: str | None = None, finish_reason: str | None = None,
        elapsed_ms: int | None = None, ttft_ms: int | None = None,
        usage: Any = None, selected_model_id: str | None = None,
        selected_provider: str | None = None,
        selected_upstream_model: str | None = None,
        selected_route_id: str | None = None,
        actual_response_model: str | None = None, route_mode: str | None = None,
        fallback_used: bool = False, fallback_depth: int = 0,
        credential_source: str = CREDENTIAL_POOL,
    ) -> CallRecord:
        prompt, completion, total, reasoning, token_source = token_evidence(usage)
        estimated_usd, estimated_krw, basis = cost_estimate(
            actual_response_model or selected_model_id, prompt, completion
        )
        origin = self.origin or {}
        return CallRecord(
            log_id=self.log_id, request_id=self.request_id, endpoint=self.endpoint,
            product=origin.get("product") or "unknown",
            origin_source=ORIGIN_DECLARED if origin.get("product") not in (None, "unknown")
            else ORIGIN_UNKNOWN,
            origin_request_id=origin.get("origin_request_id"),
            subject_ref=origin.get("subject_ref"), tenant_ref=origin.get("tenant_ref"),
            membership_tier=origin.get("membership_tier"),
            client_app=origin.get("client_app"),
            client_version=origin.get("client_version"),
            session_ref=origin.get("session_ref"),
            requested_model_id=self.requested_model_id,
            selected_model_id=selected_model_id, selected_provider=selected_provider,
            selected_upstream_model=selected_upstream_model,
            selected_route_id=selected_route_id,
            actual_response_model=actual_response_model, route_mode=route_mode,
            streaming=self.streaming, protocol=self.protocol, outcome=outcome,
            http_status=http_status, error_code=error_code, finish_reason=finish_reason,
            started_at=self.started_at, finished_at=utc_now_iso(),
            elapsed_ms=elapsed_ms,
            latency_source=LATENCY_MEASURED if elapsed_ms is not None else LATENCY_UNKNOWN,
            ttft_ms=ttft_ms if ttft_ms is not None else self.ttft_ms, attempt_count=self.attempt_count,
            fallback_used=fallback_used, fallback_depth=fallback_depth,
            prompt_tokens=prompt, completion_tokens=completion, total_tokens=total,
            reasoning_tokens=reasoning, token_source=token_source,
            estimated_usd=estimated_usd, estimated_krw=estimated_krw, cost_basis=basis,
            credential_source=credential_source,
            attempts=tuple(self.attempts),
        )
