"""Cross-runtime projection of Core Memory Read/Retrieval and Write/Receipt
authority through Engine (#1748 E3A/E3B).

The Engine owns only the trusted internal wire and the server-side binding
registry. Namespace authorization, retrieval budgets, ranking, untrusted-context
assembly and provenance omission remain Padiem AI Core authority: this module
reuses ``authorize_memory_retrieval``, ``prepare_retrieval_context`` and
``rank_retrieval_results`` without re-implementing any of their semantics.

Callers can never submit storage endpoints, providers, credentials, raw
authorizations or private source references. A request is narrowed to the
readable namespaces of the trusted ``EngineMemoryBinding`` registered for the
authenticated app; without such a server-side binding the route fails closed.
Retrieved content is projected only through Core's public retrieval/context
dictionaries, which keep every reference UNTRUSTED_REFERENCE and omit private
source data.

E3B adds the write half with the same posture and a strictly separate
authority: the caller submits only a bounded candidate (ids, namespace
selector, content, idempotency key and an optional proposal reference), while
``MemoryWriteOrigin`` classification, provenance, ``MemoryWriteAuthorization``,
``MemoryWritePolicy`` and the idempotent storage adapter come exclusively from
a server-side ``EngineMemoryWriteBinding``. Core remains the only gate:
``authorize_memory_write`` -> ``persist_authorized_memory_write`` ->
``validate_memory_write_receipt``. A model-proposed candidate without an
independently approved proposal never reaches an adapter, and a read binding
never implies write authority.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import json
from typing import Any, Mapping

from padiem_ai_core.memory import (
    MemoryContractError,
    MemoryNamespace,
    MemoryProvenance,
    MemoryScope,
    MemoryWriteAuthorization,
    MemoryWriteOrigin,
    MemoryWritePolicy,
    MemoryWriteRequest,
    authorize_memory_write,
)
from padiem_ai_core.memory_context import rank_retrieval_results
from padiem_ai_core.memory_read import (
    MemoryReadAuthorization,
    MemoryReadPolicy,
    authorize_memory_retrieval,
)
from padiem_ai_core.memory_receipt import (
    IdempotentMemoryWriteAdapter,
    persist_authorized_memory_write,
)
from padiem_ai_core.retrieval import (
    MAX_RETRIEVAL_NAMESPACES,
    MAX_RETRIEVAL_QUERY_CHARS,
    MAX_RETRIEVAL_RESULTS,
    RetrievalContractError,
    RetrievalProvider,
    RetrievalRequest,
    prepare_retrieval_context,
)

from app.service import ServiceResponse, _service_error

MEMORY_PATH = "/internal/v1/memory/retrieve"
MEMORY_WRITE_PATH = "/internal/v1/memory/write"
MAX_MEMORY_REQUEST_BODY_BYTES = 32 * 1024

_TOP_LEVEL_REQUIRED = frozenset({"app_id", "query", "namespaces"})
_TOP_LEVEL_ALLOWED = frozenset(
    {"app_id", "query", "namespaces", "max_results", "trace_id"}
)
_NAMESPACE_ALLOWED = frozenset({"scope", "subject_id"})
_DEFAULT_MAX_RESULTS = 8

_WRITE_TOP_REQUIRED = frozenset(
    {"app_id", "memory_id", "namespace", "content", "idempotency_key"}
)
_WRITE_TOP_ALLOWED = _WRITE_TOP_REQUIRED | frozenset({"proposal_id", "trace_id"})
_WRITE_FORBIDDEN_403_CODES = frozenset(
    {
        "memory_namespace_not_authorized",
        "memory_app_mismatch",
        "memory_scope_not_allowed",
        "memory_origin_not_allowed",
        "model_memory_approval_required",
    }
)
_WRITE_RECEIPT_502_CODES = frozenset(
    {"invalid_memory_receipt", "memory_receipt_mismatch"}
)


class MemoryWireError(ValueError):
    def __init__(self, code: str, safe_message: str, *, status_code: int = 400) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class EngineMemoryBinding:
    """Server-owned read authority plus the injected Core retrieval provider."""

    authorization: MemoryReadAuthorization
    provider: RetrievalProvider
    read_policy: MemoryReadPolicy = field(default_factory=MemoryReadPolicy)

    def __post_init__(self) -> None:
        if not isinstance(self.authorization, MemoryReadAuthorization):
            raise MemoryContractError(
                "invalid_memory_read_authorization",
                "binding authorization must be MemoryReadAuthorization",
            )
        if not callable(getattr(self.provider, "retrieve", None)):
            raise MemoryContractError(
                "invalid_memory_binding",
                "binding provider must expose an async retrieve(request) method",
            )
        if not isinstance(self.read_policy, MemoryReadPolicy):
            raise MemoryContractError(
                "invalid_memory_read_policy",
                "binding read_policy must be MemoryReadPolicy",
            )


@dataclass(frozen=True, slots=True)
class MemoryRetrievalWireRequest:
    app_id: str
    query: str
    namespaces: tuple[MemoryNamespace, ...]
    max_results: int
    trace_id: str | None


def _exact_object(
    value: Any,
    *,
    name: str,
    allowed: frozenset[str],
    required: frozenset[str],
    code: str = "invalid_memory_request",
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise MemoryWireError(code, f"{name} must be an object.")
    data = dict(value)
    if set(data) - allowed:
        raise MemoryWireError(code, f"{name} contains unsupported fields.")
    if required - set(data):
        raise MemoryWireError(code, f"{name} is missing required fields.")
    return data


def _trace_id(value: Any, *, code: str = "invalid_memory_request") -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise MemoryWireError(code, "trace_id must be a bounded string.")
    return value.strip()


def build_memory_retrieval_request(payload: Any) -> MemoryRetrievalWireRequest:
    data = _exact_object(
        payload,
        name="request",
        allowed=_TOP_LEVEL_ALLOWED,
        required=_TOP_LEVEL_REQUIRED,
    )

    app_id = data["app_id"]
    if not isinstance(app_id, str) or not app_id.strip():
        raise MemoryWireError("invalid_memory_request", "app_id must be a non-empty string.")
    app_id = app_id.strip()

    query = data["query"]
    if not isinstance(query, str):
        raise MemoryWireError("invalid_memory_request", "query must be a non-empty string.")
    query = query.strip()
    if not query or len(query) > MAX_RETRIEVAL_QUERY_CHARS:
        raise MemoryWireError("invalid_memory_request", "query exceeds the bounded retrieval limit.")

    raw_namespaces = data["namespaces"]
    if (
        isinstance(raw_namespaces, (str, bytes))
        or not isinstance(raw_namespaces, (list, tuple))
        or not 1 <= len(raw_namespaces) <= MAX_RETRIEVAL_NAMESPACES
    ):
        raise MemoryWireError(
            "invalid_memory_request",
            f"namespaces must contain 1 to {MAX_RETRIEVAL_NAMESPACES} objects.",
        )

    namespaces: list[MemoryNamespace] = []
    for entry in raw_namespaces:
        ns_data = _exact_object(
            entry,
            name="namespaces[]",
            allowed=_NAMESPACE_ALLOWED,
            required=_NAMESPACE_ALLOWED,
        )
        scope = ns_data["scope"]
        if not isinstance(scope, str):
            raise MemoryWireError("invalid_memory_request", "namespace scope must be a string.")
        try:
            namespaces.append(
                MemoryNamespace(
                    # The owning app is always the authenticated caller app;
                    # the wire can never name another app's namespace.
                    app_id=app_id,
                    scope=MemoryScope(scope),
                    subject_id=ns_data["subject_id"],
                )
            )
        except (ValueError, KeyError):
            raise MemoryWireError(
                "invalid_memory_request",
                "namespace scope/subject_id is invalid for the memory contract.",
            ) from None

    max_results = data.get("max_results")
    if max_results is None:
        max_results = _DEFAULT_MAX_RESULTS
    if (
        isinstance(max_results, bool)
        or not isinstance(max_results, int)
        or not 1 <= max_results <= MAX_RETRIEVAL_RESULTS
    ):
        raise MemoryWireError(
            "invalid_memory_request",
            f"max_results must be between 1 and {MAX_RETRIEVAL_RESULTS}.",
        )

    return MemoryRetrievalWireRequest(
        app_id=app_id,
        query=query,
        namespaces=tuple(namespaces),
        max_results=max_results,
        trace_id=_trace_id(data.get("trace_id")),
    )


@dataclass(frozen=True, slots=True)
class MemoryWriteWireRequest:
    """Non-authority write candidate parsed from the internal wire.

    Deliberately carries no origin, provenance, authorization, policy,
    adapter, storage reference or credential field: those are server-side
    authority supplied only by the trusted ``EngineMemoryWriteBinding``.
    """

    app_id: str
    memory_id: str
    namespace: MemoryNamespace
    content: str
    idempotency_key: str
    proposal_id: str | None
    trace_id: str | None


@dataclass(frozen=True, slots=True)
class MemoryWriteClassification:
    """Trusted classifier output: origin plus server-side provenance."""

    origin: MemoryWriteOrigin
    provenance: MemoryProvenance

    def __post_init__(self) -> None:
        if not isinstance(self.origin, MemoryWriteOrigin):
            raise MemoryContractError(
                "invalid_memory_write_classification",
                "classification origin must be MemoryWriteOrigin",
            )
        if not isinstance(self.provenance, MemoryProvenance):
            raise MemoryContractError(
                "invalid_memory_write_classification",
                "classification provenance must be MemoryProvenance",
            )


@dataclass(frozen=True, slots=True)
class EngineMemoryWriteBinding:
    """Server-owned write authority plus the injected idempotent adapter.

    The classifier is trusted deployment code (Control Plane / Product
    attestation): it alone decides ``MemoryWriteOrigin`` and builds
    ``MemoryProvenance`` from independently verified server state. The wire
    can never select an origin or attach its own provenance.
    """

    authorization: MemoryWriteAuthorization
    adapter: IdempotentMemoryWriteAdapter
    classifier: Callable[[MemoryWriteWireRequest], MemoryWriteClassification]
    write_policy: MemoryWritePolicy = field(default_factory=MemoryWritePolicy)

    def __post_init__(self) -> None:
        if not isinstance(self.authorization, MemoryWriteAuthorization):
            raise MemoryContractError(
                "invalid_memory_write_authorization",
                "binding authorization must be MemoryWriteAuthorization",
            )
        if not callable(getattr(self.adapter, "write", None)):
            raise MemoryContractError(
                "invalid_memory_write_binding",
                "binding adapter must expose an async write(request) method",
            )
        if not callable(self.classifier):
            raise MemoryContractError(
                "invalid_memory_write_binding",
                "binding classifier must be a callable candidate -> classification",
            )
        if not isinstance(self.write_policy, MemoryWritePolicy):
            raise MemoryContractError(
                "invalid_memory_write_policy",
                "binding write_policy must be MemoryWritePolicy",
            )


def _optional_identifier(value: Any, *, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise MemoryWireError("invalid_memory_write_request", f"{name} must be a non-empty string.")
    return value.strip()


def _required_identifier(value: Any, *, name: str) -> str:
    checked = _optional_identifier(value, name=name)
    if checked is None:
        raise MemoryWireError("invalid_memory_write_request", f"{name} must be a non-empty string.")
    return checked


def build_memory_write_request(payload: Any) -> MemoryWriteWireRequest:
    data = _exact_object(
        payload,
        name="request",
        allowed=_WRITE_TOP_ALLOWED,
        required=_WRITE_TOP_REQUIRED,
        code="invalid_memory_write_request",
    )

    app_id = data["app_id"]
    if not isinstance(app_id, str) or not app_id.strip():
        raise MemoryWireError("invalid_memory_write_request", "app_id must be a non-empty string.")
    app_id = app_id.strip()

    content = data["content"]
    if not isinstance(content, str):
        raise MemoryWireError("invalid_memory_write_request", "content must be a string.")

    ns_data = _exact_object(
        data["namespace"],
        name="namespace",
        allowed=_NAMESPACE_ALLOWED,
        required=_NAMESPACE_ALLOWED,
        code="invalid_memory_write_request",
    )
    scope = ns_data["scope"]
    if not isinstance(scope, str):
        raise MemoryWireError("invalid_memory_write_request", "namespace scope must be a string.")
    try:
        namespace = MemoryNamespace(
            # The owning app is always the authenticated caller app; the wire
            # can never name another app's namespace.
            app_id=app_id,
            scope=MemoryScope(scope),
            subject_id=ns_data["subject_id"],
        )
    except (ValueError, KeyError):
        raise MemoryWireError(
            "invalid_memory_write_request",
            "namespace scope/subject_id is invalid for the memory contract.",
        ) from None

    return MemoryWriteWireRequest(
        app_id=app_id,
        memory_id=_required_identifier(data["memory_id"], name="memory_id"),
        namespace=namespace,
        content=content,
        idempotency_key=_required_identifier(data["idempotency_key"], name="idempotency_key"),
        proposal_id=_optional_identifier(data.get("proposal_id"), name="proposal_id"),
        trace_id=_trace_id(data.get("trace_id"), code="invalid_memory_write_request"),
    )


def _memory_contract_error(exc: MemoryContractError) -> ServiceResponse:
    if exc.code in {"memory_namespace_not_authorized", "memory_app_mismatch", "memory_scope_not_allowed"}:
        return _service_error(exc.code, exc.safe_message, status_code=403)
    if exc.code == "memory_read_budget_exceeded":
        return _service_error(exc.code, exc.safe_message, status_code=422)
    return _service_error(exc.code, exc.safe_message, status_code=400)


def _memory_write_contract_error(exc: MemoryContractError) -> ServiceResponse:
    # Authorization, scope, origin and model-approval gates are authority
    # failures (403); budgets are 422; a bad adapter receipt is an upstream
    # fault (502) and is never re-projected as success.
    if exc.code in _WRITE_FORBIDDEN_403_CODES:
        return _service_error(exc.code, exc.safe_message, status_code=403)
    if exc.code in _WRITE_RECEIPT_502_CODES:
        return _service_error(
            exc.code,
            "The bound memory write adapter returned invalid storage evidence.",
            status_code=502,
        )
    if exc.code == "memory_budget_exceeded":
        return _service_error(exc.code, exc.safe_message, status_code=422)
    return _service_error(exc.code, exc.safe_message, status_code=400)


def _retrieval_contract_error(exc: RetrievalContractError) -> ServiceResponse:
    # Provider-side contract/scope/budget failures are upstream faults; the
    # Engine never re-projects retrieved content as trusted data.
    return _service_error(exc.code, exc.safe_message, status_code=502)


def _empty_retrieval_body(
    *,
    request: MemoryRetrievalWireRequest,
    retrieval_request: RetrievalRequest,
) -> dict[str, Any]:
    # NO_RESULT is an explicit empty projection, never an invented memory.
    return {
        "ok": True,
        "app_id": request.app_id,
        "trace_id": request.trace_id,
        "trust": "untrusted_reference",
        "retrieval": {"item_count": 0, "items": [], "context": None},
        "ranking": [],
        "requested_namespaces": list(retrieval_request.namespaces),
        "max_results": retrieval_request.max_results,
    }


def _public_result(
    *,
    request: MemoryRetrievalWireRequest,
    retrieval_request: RetrievalRequest,
    prepared: Any,
) -> ServiceResponse:
    ranked = rank_retrieval_results(prepared.items)
    body: dict[str, Any] = {
        "ok": True,
        "app_id": request.app_id,
        "trace_id": request.trace_id,
        "trust": "untrusted_reference",
        "retrieval": prepared.to_public_dict(),
        "ranking": [entry.to_public_dict() for entry in ranked],
        "requested_namespaces": list(retrieval_request.namespaces),
        "max_results": retrieval_request.max_results,
    }
    return ServiceResponse(status_code=200, body=body)


class MemoryRetrievalEngineService:
    """Bounded internal Engine projection over Core memory read and write.

    Read and write authority are deliberately separate registries: a bound
    read binding never implies write capability, and vice versa. There is no
    shared "memory enabled" flag.
    """

    def __init__(
        self,
        *,
        bindings: Mapping[str, EngineMemoryBinding] | None = None,
        write_bindings: Mapping[str, EngineMemoryWriteBinding] | None = None,
    ) -> None:
        registry = dict(bindings or {})
        for app_id, binding in registry.items():
            if not isinstance(app_id, str) or not app_id:
                raise ValueError("memory binding keys must be non-empty app ids")
            if not isinstance(binding, EngineMemoryBinding):
                raise ValueError("memory bindings must be EngineMemoryBinding values")
            if binding.authorization.app_id != app_id:
                raise MemoryContractError(
                    "memory_app_mismatch",
                    "memory binding must be registered under its own authorized app",
                )
        self._bindings: dict[str, EngineMemoryBinding] = registry

        write_registry = dict(write_bindings or {})
        for app_id, binding in write_registry.items():
            if not isinstance(app_id, str) or not app_id:
                raise ValueError("memory write binding keys must be non-empty app ids")
            if not isinstance(binding, EngineMemoryWriteBinding):
                raise ValueError(
                    "memory write bindings must be EngineMemoryWriteBinding values"
                )
            if binding.authorization.app_id != app_id:
                raise MemoryContractError(
                    "memory_app_mismatch",
                    "memory write binding must be registered under its own authorized app",
                )
        self._write_bindings: dict[str, EngineMemoryWriteBinding] = write_registry

    @property
    def bound_app_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._bindings))

    @property
    def write_bound_app_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._write_bindings))

    async def retrieve_payload(self, payload: Any) -> ServiceResponse:
        requested_app = payload.get("app_id") if isinstance(payload, Mapping) else None
        binding = self._bindings.get(requested_app) if isinstance(requested_app, str) else None
        if binding is None:
            # Fail closed before interpreting the wire: no trusted server-side
            # memory binding means the Engine must never reach a storage
            # provider on the caller's word.
            return _service_error(
                "memory_binding_unavailable",
                "No trusted memory binding is registered for this application.",
                status_code=503,
                retryable=True,
            )

        try:
            request = build_memory_retrieval_request(payload)
        except MemoryWireError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        try:
            retrieval_request = authorize_memory_retrieval(
                query=request.query,
                namespaces=request.namespaces,
                authorization=binding.authorization,
                max_results=request.max_results,
                policy=binding.read_policy,
            )
        except MemoryContractError as exc:
            return _memory_contract_error(exc)

        try:
            items = await binding.provider.retrieve(retrieval_request)
        except Exception:
            return _service_error(
                "memory_provider_unavailable",
                "The bound memory retrieval provider is unavailable.",
                status_code=503,
                retryable=True,
            )

        if isinstance(items, (str, bytes)) or not items:
            return ServiceResponse(
                status_code=200,
                body=_empty_retrieval_body(
                    request=request,
                    retrieval_request=retrieval_request,
                ),
            )

        try:
            prepared = prepare_retrieval_context(retrieval_request, items)
        except RetrievalContractError as exc:
            if exc.code == "no_retrieval_context":
                return ServiceResponse(
                    status_code=200,
                    body=_empty_retrieval_body(
                        request=request,
                        retrieval_request=retrieval_request,
                    ),
                )
            return _retrieval_contract_error(exc)
        except (TypeError, ValueError, OverflowError):
            return _service_error(
                "invalid_retrieval_result",
                "The memory retrieval provider returned an invalid result.",
                status_code=502,
            )

        try:
            return _public_result(
                request=request,
                retrieval_request=retrieval_request,
                prepared=prepared,
            )
        except RetrievalContractError as exc:
            return _retrieval_contract_error(exc)
        except Exception:
            return _service_error(
                "engine_internal_error",
                "Padiem AI Engine memory retrieval failed.",
                status_code=500,
            )

    async def write_payload(self, payload: Any) -> ServiceResponse:
        requested_app = payload.get("app_id") if isinstance(payload, Mapping) else None
        binding = (
            self._write_bindings.get(requested_app)
            if isinstance(requested_app, str)
            else None
        )
        if binding is None:
            # Fail closed before interpreting the wire: request JSON is not
            # memory write authority, and without a trusted server-side write
            # binding no storage adapter may ever be reached on the caller's
            # word. A read binding never implies this authority.
            return _service_error(
                "memory_write_binding_unavailable",
                "No trusted memory write binding is registered for this application.",
                status_code=503,
                retryable=True,
            )

        try:
            request = build_memory_write_request(payload)
        except MemoryWireError as exc:
            return _service_error(exc.code, exc.safe_message, status_code=exc.status_code)

        try:
            classification = binding.classifier(request)
        except MemoryContractError as exc:
            return _memory_write_contract_error(exc)
        except Exception:
            return _service_error(
                "memory_write_authority_unavailable",
                "The trusted memory write authority failed to classify the candidate.",
                status_code=503,
                retryable=True,
            )
        if not isinstance(classification, MemoryWriteClassification):
            return _service_error(
                "memory_write_authority_unavailable",
                "The trusted memory write authority returned an invalid classification.",
                status_code=503,
                retryable=True,
            )

        try:
            # Core owns every durable-write gate: origin/namespace/scope/
            # budget checks plus the mandatory independent approval for
            # model-proposed candidates. Nothing here re-implements them.
            write_request = MemoryWriteRequest(
                memory_id=request.memory_id,
                namespace=request.namespace,
                content=request.content,
                origin=classification.origin,
                provenance=classification.provenance,
                idempotency_key=request.idempotency_key,
                proposal_id=request.proposal_id,
            )
            prepared = authorize_memory_write(
                write_request,
                binding.authorization,
                policy=binding.write_policy,
            )
        except MemoryContractError as exc:
            return _memory_write_contract_error(exc)

        try:
            # persist_authorized_memory_write is the only path to the
            # adapter: the receipt is validated by Core before any success
            # is projected, and a bad receipt can never become a success.
            receipt = await persist_authorized_memory_write(prepared, binding.adapter)
        except MemoryContractError as exc:
            return _memory_write_contract_error(exc)
        except Exception:
            return _service_error(
                "memory_write_provider_unavailable",
                "The bound memory write adapter is unavailable.",
                status_code=503,
                retryable=True,
            )

        return ServiceResponse(
            status_code=200,
            body={
                "ok": True,
                "app_id": request.app_id,
                "trace_id": request.trace_id,
                # Core public projections only: no storage_ref, no private
                # provenance source_ref, no content bytes.
                "receipt": receipt.to_public_dict(),
                "write": prepared.to_public_dict(),
            },
        )

    async def handle(
        self,
        *,
        method: str,
        path: str,
        content_type: str | None = None,
        body: bytes = b"",
    ) -> ServiceResponse:
        normalized_method = method.upper() if isinstance(method, str) else ""
        if path not in (MEMORY_PATH, MEMORY_WRITE_PATH):
            return _service_error(
                "not_found",
                "Internal Engine route not found.",
                status_code=404,
            )
        if normalized_method != "POST":
            return _service_error(
                "method_not_allowed",
                "Method not allowed.",
                status_code=405,
            )
        if (
            not isinstance(content_type, str)
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            return _service_error(
                "unsupported_media_type",
                "Content-Type must be application/json.",
                status_code=415,
            )
        if not isinstance(body, (bytes, bytearray, memoryview)):
            return _service_error(
                "invalid_request",
                "Request body is invalid.",
                status_code=400,
            )
        raw = bytes(body)
        if len(raw) > MAX_MEMORY_REQUEST_BODY_BYTES:
            return _service_error(
                "request_too_large",
                "Request body exceeds the internal Engine safety limit.",
                status_code=413,
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return _service_error(
                "invalid_json",
                "Request body must contain valid UTF-8 JSON.",
                status_code=400,
            )
        if path == MEMORY_WRITE_PATH:
            return await self.write_payload(payload)
        return await self.retrieve_payload(payload)
