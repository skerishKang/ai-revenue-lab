"""Canonical B14 per-model request-parameter profiles (#3977).

Authority: ``docs/architecture/B14_MODEL_PROVIDER_EXECUTION_AUTHORITY_2026-10-10.md``
and ``docs/models/final-evaluation/B14_OFFICIAL_PARAMETER_REVALIDATION_2026-10-10.md``.

B14 executes the user's *exact* manually chosen registered provider/model. It does
not invent sampling, reasoning or output values. This module is the single source
of truth for:

* which **optional** request fields each exact model's serving API accepts;
* the exact upstream JSON shape each supported field must be sent in;
* the provenance (manufacturer vs. provider variant) and the evidence level of
  every claim;
* the separation of ``max input context`` / ``model max output`` /
  ``serving max output`` / ``request output budget``.

Design rules (fail-closed):

* ``temperature`` and ``max_tokens`` are the OpenAI-compatible **transport
  baseline** every registered provider endpoint advertises. They are forwarded
  only when the caller sets them; an omitted value is never replaced by a
  synthetic default.
* Any other optional field is forwarded **only** when the exact model's profile
  documents support. An explicit request for an undocumented field is rejected
  with an explainable error — it is never silently dropped, rewritten, or mapped
  to a different value.
* A model with no documented provenance or parameter support stays ``UNKNOWN``.
  Unknown is never turned into an invented capability or default.

This module holds no credentials and performs no network call.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

PROFILE_SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# Output-budget authorities (#3553 / #3977)
# ---------------------------------------------------------------------------
# An EXPLICIT request output budget is bounded by a B14 *service* ceiling. This
# is a resource-protection limit, NOT any model's maximum output, and it is
# never presented as model capability. A model's own documented maximum, when
# known, is a separate, stricter authority (``ModelParameterProfile.model_max_output``).
B14_OPERATIONAL_REQUEST_TOKEN_CEILING = 4096

# Evidence levels, ordered from strongest to weakest. Kept explicit so a claim
# can never be silently upgraded (B14_MODEL_PROVIDER_EXECUTION_AUTHORITY §4).
EVIDENCE_OFFICIAL_DOC = "official_doc"
EVIDENCE_PROVIDER_AUTHENTICATED_MODELS = "provider_authenticated_models"
EVIDENCE_PROVIDER_DIRECT_POST = "provider_direct_post"
EVIDENCE_B14_OPERATIONAL_POST = "b14_operational_post"
EVIDENCE_UNVERIFIED = "unverified"

# Variant classes (B14_MODEL_PROVIDER_EXECUTION_AUTHORITY §2).
VARIANT_MANUFACTURER_UNMODIFIED = "manufacturer_unmodified"
VARIANT_PROVIDER_VARIANT = "provider_variant"
VARIANT_UNKNOWN = "unknown"

# The canonical B14 optional request fields (beyond the transport baseline).
# Only these names may appear at the top level of a B14 chat-completions body.
CANONICAL_OPTIONAL_FIELDS: tuple[str, ...] = (
    "top_p",
    "top_k",
    "reasoning_effort",
    "thinking",
)

_VALUE_KIND_NUMBER = "number"
_VALUE_KIND_INTEGER = "integer"
_VALUE_KIND_BOOLEAN = "boolean"
_VALUE_KIND_ENUM = "enum"


@dataclass(frozen=True, slots=True)
class ParameterRule:
    """One supported optional request field for one exact model.

    ``upstream_path`` is the exact upstream JSON location the value must be sent
    at (a tuple so nested shapes such as ``chat_template_kwargs.enable_thinking``
    are representable). ``evidence`` records why this field is believed
    supported; it is descriptive metadata, never a runtime default.
    """

    name: str
    upstream_path: tuple[str, ...]
    value_kind: str
    minimum: float | None = None
    maximum: float | None = None
    allowed: tuple[str, ...] = ()
    evidence: str = ""


@dataclass(frozen=True, slots=True)
class ModelParameterProfile:
    """Documented parameter contract for one B14 exact model id."""

    b14_id: str
    serving_provider_id: str
    serving_api_origin: str
    upstream_model: str

    model_developer: str
    base_model_id: str | None
    variant_kind: str
    variant_evidence: str

    manufacturer_doc_url: str | None
    manufacturer_doc_checked_at: str | None
    provider_doc_url: str | None
    provider_doc_checked_at: str | None
    provider_authenticated_models_evidence: str

    rules: tuple[ParameterRule, ...] = ()
    # Informational native/recommended defaults. NEVER auto-injected; a caller
    # that omits a value relies on the provider's own default.
    native_defaults: Mapping[str, Any] = field(default_factory=dict)

    max_input_context: int | None = None
    model_max_output: int | None = None
    serving_max_output: int | None = None
    request_budget_contract: str = "explicit_only_bounded_by_b14_service_ceiling"

    evidence_level: str = EVIDENCE_UNVERIFIED
    passthrough_test: str = "NOT_TESTED"

    def rule(self, name: str) -> ParameterRule | None:
        for candidate in self.rules:
            if candidate.name == name:
                return candidate
        return None

    @property
    def supported_optional_fields(self) -> tuple[str, ...]:
        return tuple(rule.name for rule in self.rules)


# ---------------------------------------------------------------------------
# Registry — one entry per registered B14 exact model id.
# ---------------------------------------------------------------------------
# Sources checked 2026-10-10 (see the two authority documents above):
#   * Google Gemini 3 guide + official thinking settings -> reasoning_effort
#     levels; Google OpenAI-compatible surface -> top_p.
#   * Google Gemma 4 model card -> recommended sampling temperature/top_p/top_k.
#   * #3906 -> Poolside/Agnes chat_template_kwargs.enable_thinking mapping and
#     Atria reasoning_effort direct-call observation ("none" returned HTTP 422).
_GOOGLE_GEMINI_RULES = (
    ParameterRule(
        name="top_p",
        upstream_path=("top_p",),
        value_kind=_VALUE_KIND_NUMBER,
        minimum=0.0,
        maximum=1.0,
        evidence="Google Gemini OpenAI-compatible sampling surface (top_p).",
    ),
    ParameterRule(
        name="reasoning_effort",
        upstream_path=("reasoning_effort",),
        value_kind=_VALUE_KIND_ENUM,
        allowed=("minimal", "low", "medium", "high"),
        evidence="Google Gemini thinking settings via OpenAI-compatible reasoning_effort (#3906).",
    ),
)

_GOOGLE_GEMMA_RULES = (
    ParameterRule(
        name="top_p",
        upstream_path=("top_p",),
        value_kind=_VALUE_KIND_NUMBER,
        minimum=0.0,
        maximum=1.0,
        evidence="Gemma 4 official model card recommended sampling (top_p=0.95).",
    ),
    ParameterRule(
        name="top_k",
        upstream_path=("top_k",),
        value_kind=_VALUE_KIND_INTEGER,
        minimum=1,
        evidence="Gemma 4 official model card recommended sampling (top_k=64).",
    ),
)

_POOLSIDE_THINKING_RULE = ParameterRule(
    name="thinking",
    upstream_path=("chat_template_kwargs", "enable_thinking"),
    value_kind=_VALUE_KIND_BOOLEAN,
    evidence="Poolside standard request maps thinking to chat_template_kwargs.enable_thinking (#3906).",
)

_AGNES_THINKING_RULE = ParameterRule(
    name="thinking",
    upstream_path=("chat_template_kwargs", "enable_thinking"),
    value_kind=_VALUE_KIND_BOOLEAN,
    evidence="Agnes direct chat_template_kwargs.enable_thinking observation (#3906).",
)

_ATRIA_REASONING_RULE = ParameterRule(
    name="reasoning_effort",
    upstream_path=("reasoning_effort",),
    value_kind=_VALUE_KIND_ENUM,
    allowed=("low", "medium", "high"),
    evidence="Atria direct reasoning_effort observation; 'none' returned HTTP 422 (#3906).",
)

_GOOGLE_DOC = "https://ai.google.dev/gemini-api/docs/gemini-3"
_GOOGLE_THINKING_DOC = "https://ai.google.dev/gemini-api/docs/thinking"
_GEMMA_DOC = "https://ai.google.dev/gemma/docs/core/model_card_4"
_SENSENOVA_DOC = "https://github.com/OpenSenseNova/SenseNova6.8/blob/main/API.md"

PROFILES: dict[str, ModelParameterProfile] = {
    "google/gemini-3.1-flash-lite": ModelParameterProfile(
        b14_id="google/gemini-3.1-flash-lite",
        serving_provider_id="google",
        serving_api_origin="https://generativelanguage.googleapis.com/v1beta/openai",
        upstream_model="gemini-3.1-flash-lite",
        model_developer="Google",
        base_model_id=None,
        variant_kind=VARIANT_MANUFACTURER_UNMODIFIED,
        variant_evidence="Manufacturer-hosted Gemini model served by Google's own API.",
        manufacturer_doc_url=_GOOGLE_DOC,
        manufacturer_doc_checked_at="2026-10-10",
        provider_doc_url=_GOOGLE_THINKING_DOC,
        provider_doc_checked_at="2026-10-10",
        provider_authenticated_models_evidence="provider_authenticated_models_not_retested",
        rules=_GOOGLE_GEMINI_RULES,
        native_defaults={"temperature": 1.0},
        max_input_context=1048576,
        model_max_output=None,
        serving_max_output=None,
        evidence_level=EVIDENCE_OFFICIAL_DOC,
    ),
    "google/gemini-3.5-flash-lite": ModelParameterProfile(
        b14_id="google/gemini-3.5-flash-lite",
        serving_provider_id="google",
        serving_api_origin="https://generativelanguage.googleapis.com/v1beta/openai",
        upstream_model="gemini-3.5-flash-lite",
        model_developer="Google",
        base_model_id=None,
        variant_kind=VARIANT_MANUFACTURER_UNMODIFIED,
        variant_evidence="Manufacturer-hosted Gemini model served by Google's own API.",
        manufacturer_doc_url=_GOOGLE_DOC,
        manufacturer_doc_checked_at="2026-10-10",
        provider_doc_url=_GOOGLE_THINKING_DOC,
        provider_doc_checked_at="2026-10-10",
        provider_authenticated_models_evidence="provider_authenticated_models_not_retested",
        rules=_GOOGLE_GEMINI_RULES,
        native_defaults={"temperature": 1.0},
        max_input_context=1048576,
        model_max_output=None,
        serving_max_output=None,
        evidence_level=EVIDENCE_OFFICIAL_DOC,
    ),
    "google/gemma-4-26b-a4b-it": ModelParameterProfile(
        b14_id="google/gemma-4-26b-a4b-it",
        serving_provider_id="google",
        serving_api_origin="https://generativelanguage.googleapis.com/v1beta/openai",
        upstream_model="gemma-4-26b-a4b-it",
        model_developer="Google",
        base_model_id=None,
        variant_kind=VARIANT_MANUFACTURER_UNMODIFIED,
        variant_evidence="Manufacturer-hosted Gemma model served by Google's own API.",
        manufacturer_doc_url=_GEMMA_DOC,
        manufacturer_doc_checked_at="2026-10-10",
        provider_doc_url=_GEMMA_DOC,
        provider_doc_checked_at="2026-10-10",
        provider_authenticated_models_evidence="provider_authenticated_models_not_retested",
        rules=_GOOGLE_GEMMA_RULES,
        native_defaults={"temperature": 1.0, "top_p": 0.95, "top_k": 64},
        max_input_context=262144,
        model_max_output=None,
        serving_max_output=None,
        evidence_level=EVIDENCE_OFFICIAL_DOC,
    ),
    "google/gemma-4-31b-it": ModelParameterProfile(
        b14_id="google/gemma-4-31b-it",
        serving_provider_id="google",
        serving_api_origin="https://generativelanguage.googleapis.com/v1beta/openai",
        upstream_model="gemma-4-31b-it",
        model_developer="Google",
        base_model_id=None,
        variant_kind=VARIANT_MANUFACTURER_UNMODIFIED,
        variant_evidence="Manufacturer-hosted Gemma model served by Google's own API.",
        manufacturer_doc_url=_GEMMA_DOC,
        manufacturer_doc_checked_at="2026-10-10",
        provider_doc_url=_GEMMA_DOC,
        provider_doc_checked_at="2026-10-10",
        provider_authenticated_models_evidence="provider_authenticated_models_not_retested",
        rules=_GOOGLE_GEMMA_RULES,
        native_defaults={"temperature": 1.0, "top_p": 0.95, "top_k": 64},
        max_input_context=262144,
        model_max_output=None,
        serving_max_output=None,
        evidence_level=EVIDENCE_OFFICIAL_DOC,
    ),
    "sensenova/sensenova-6.8-flash-lite": ModelParameterProfile(
        b14_id="sensenova/sensenova-6.8-flash-lite",
        serving_provider_id="sensenova",
        serving_api_origin="https://token.sensenova.ai/v1",
        upstream_model="sensenova-6.8-flash-lite",
        model_developer="SenseNova",
        base_model_id=None,
        variant_kind=VARIANT_MANUFACTURER_UNMODIFIED,
        variant_evidence="Manufacturer-hosted SenseNova model served by SenseNova's own API.",
        manufacturer_doc_url=_SENSENOVA_DOC,
        manufacturer_doc_checked_at="2026-10-10",
        provider_doc_url=_SENSENOVA_DOC,
        provider_doc_checked_at="2026-10-10",
        provider_authenticated_models_evidence="provider_authenticated_models_not_retested",
        rules=(),
        native_defaults={},
        max_input_context=256000,
        model_max_output=None,
        serving_max_output=None,
        evidence_level=EVIDENCE_UNVERIFIED,
    ),
    "poolside/laguna-s-2.1": ModelParameterProfile(
        b14_id="poolside/laguna-s-2.1",
        serving_provider_id="poolside",
        serving_api_origin="https://inference.poolside.ai/v1",
        upstream_model="poolside/laguna-s-2.1",
        model_developer="Poolside",
        base_model_id=None,
        variant_kind=VARIANT_MANUFACTURER_UNMODIFIED,
        variant_evidence="Manufacturer-hosted Poolside model served by Poolside's own API.",
        manufacturer_doc_url=None,
        manufacturer_doc_checked_at=None,
        provider_doc_url=None,
        provider_doc_checked_at=None,
        provider_authenticated_models_evidence="provider_authenticated_models_not_retested",
        rules=(_POOLSIDE_THINKING_RULE,),
        native_defaults={},
        max_input_context=1000000,
        model_max_output=None,
        serving_max_output=None,
        evidence_level=EVIDENCE_PROVIDER_DIRECT_POST,
    ),
    "inception/mercury-2.5": ModelParameterProfile(
        b14_id="inception/mercury-2.5",
        serving_provider_id="inception",
        serving_api_origin="https://api.inceptionlabs.ai/v1",
        upstream_model="mercury-2.5",
        model_developer="Inception Labs",
        base_model_id=None,
        variant_kind=VARIANT_MANUFACTURER_UNMODIFIED,
        variant_evidence="Manufacturer-hosted Mercury model served by Inception's own API.",
        manufacturer_doc_url=None,
        manufacturer_doc_checked_at=None,
        provider_doc_url=None,
        provider_doc_checked_at=None,
        provider_authenticated_models_evidence="provider_authenticated_models_not_retested",
        rules=(),
        native_defaults={},
        max_input_context=None,
        model_max_output=None,
        serving_max_output=None,
        evidence_level=EVIDENCE_UNVERIFIED,
    ),
    "atria/Atria-Dawn-Preview": ModelParameterProfile(
        b14_id="atria/Atria-Dawn-Preview",
        serving_provider_id="atria",
        serving_api_origin="https://api.atria-asi.ai/v1",
        upstream_model="Atria-Dawn-Preview",
        model_developer="Atria",
        base_model_id=None,
        variant_kind=VARIANT_MANUFACTURER_UNMODIFIED,
        variant_evidence="Manufacturer-hosted Atria preview model served by Atria's own API.",
        manufacturer_doc_url=None,
        manufacturer_doc_checked_at=None,
        provider_doc_url=None,
        provider_doc_checked_at=None,
        provider_authenticated_models_evidence="provider_authenticated_models_not_retested",
        rules=(_ATRIA_REASONING_RULE,),
        native_defaults={},
        max_input_context=None,
        model_max_output=None,
        serving_max_output=None,
        evidence_level=EVIDENCE_PROVIDER_DIRECT_POST,
    ),
    "agnes-ai/agnes-3.0-flash": ModelParameterProfile(
        b14_id="agnes-ai/agnes-3.0-flash",
        serving_provider_id="agnes-ai",
        serving_api_origin="https://apihub.agnes-ai.com/v1",
        upstream_model="agnes-3.0-flash",
        model_developer="UNKNOWN",
        base_model_id=None,
        variant_kind=VARIANT_UNKNOWN,
        variant_evidence=(
            "Agnes publishes the model but its upstream base/variant relationship "
            "is not documented; provenance stays UNKNOWN."
        ),
        manufacturer_doc_url=None,
        manufacturer_doc_checked_at=None,
        provider_doc_url=None,
        provider_doc_checked_at=None,
        provider_authenticated_models_evidence="provider_authenticated_models_not_retested",
        rules=(_AGNES_THINKING_RULE,),
        native_defaults={},
        max_input_context=None,
        model_max_output=None,
        serving_max_output=None,
        evidence_level=EVIDENCE_PROVIDER_DIRECT_POST,
    ),
    "experiential/qwen3.8-flash-next-uncensored": ModelParameterProfile(
        b14_id="experiential/qwen3.8-flash-next-uncensored",
        serving_provider_id="experiential",
        serving_api_origin="https://api.experientiallabs.ai/v1",
        upstream_model="qwen3.8-flash-next-uncensored",
        model_developer="Qwen (Alibaba) base, modified by Experiential Labs",
        base_model_id="qwen3.8-flash-next",
        variant_kind=VARIANT_PROVIDER_VARIANT,
        variant_evidence=(
            "Model id declares an 'uncensored' derivative; Experiential Labs "
            "documents this exact served model (GET /api/models/qwen3.8-flash-next-uncensored)."
        ),
        manufacturer_doc_url=None,
        manufacturer_doc_checked_at=None,
        provider_doc_url="https://api.experientiallabs.ai/v1",
        provider_doc_checked_at="2026-10-10",
        provider_authenticated_models_evidence="provider_public_model_detail_2026-10-10",
        rules=(),
        native_defaults={},
        max_input_context=262144,
        model_max_output=None,
        serving_max_output=None,
        evidence_level=EVIDENCE_UNVERIFIED,
    ),
}


def get_profile(b14_id: str) -> ModelParameterProfile | None:
    """Return the documented profile for an exact model id, or ``None``."""
    if not isinstance(b14_id, str):
        return None
    return PROFILES.get(b14_id.strip())


def supported_optional_fields(b14_id: str) -> tuple[str, ...]:
    """Optional request fields the exact model documents support (may be empty)."""
    profile = get_profile(b14_id)
    return profile.supported_optional_fields if profile is not None else ()


def _coerce_number(value: Any, rule: ParameterRule, model_id: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _invalid(model_id, rule.name, "숫자여야 합니다.")
    number = float(value)
    if rule.minimum is not None and number < rule.minimum:
        raise _invalid(model_id, rule.name, f"{rule.minimum} 이상이어야 합니다.")
    if rule.maximum is not None and number > rule.maximum:
        raise _invalid(model_id, rule.name, f"{rule.maximum} 이하여야 합니다.")
    return number


def _coerce_integer(value: Any, rule: ParameterRule, model_id: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _invalid(model_id, rule.name, "정수여야 합니다.")
    if rule.minimum is not None and value < rule.minimum:
        raise _invalid(model_id, rule.name, f"{int(rule.minimum)} 이상이어야 합니다.")
    if rule.maximum is not None and value > rule.maximum:
        raise _invalid(model_id, rule.name, f"{int(rule.maximum)} 이하여야 합니다.")
    return int(value)


def _coerce_boolean(value: Any, rule: ParameterRule, model_id: str) -> bool:
    if not isinstance(value, bool):
        raise _invalid(model_id, rule.name, "true 또는 false여야 합니다.")
    return value


def _coerce_enum(value: Any, rule: ParameterRule, model_id: str) -> str:
    if not isinstance(value, str) or value not in rule.allowed:
        raise _invalid(
            model_id,
            rule.name,
            "다음 중 하나여야 합니다: " + ", ".join(rule.allowed),
        )
    return value


_COERCERS = {
    _VALUE_KIND_NUMBER: _coerce_number,
    _VALUE_KIND_INTEGER: _coerce_integer,
    _VALUE_KIND_BOOLEAN: _coerce_boolean,
    _VALUE_KIND_ENUM: _coerce_enum,
}


def _invalid(model_id: str, field_name: str, detail: str):
    # Imported lazily so this module stays import-light and cycle-free.
    from app.pilot.errors import InvalidParameterValue

    return InvalidParameterValue(field_name, model_id, detail)


def _unsupported(model_id: str, field_name: str, detail: str = ""):
    from app.pilot.errors import UnsupportedParameter

    return UnsupportedParameter(field_name, model_id, detail)


def validate_optional_parameters(
    b14_id: str, provided: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate caller-supplied optional fields against the exact model profile.

    Returns only the canonical fields that were actually provided and accepted.
    Raises a 422-class ``PilotError`` for any field the exact model does not
    document, or whose value is out of the documented range. Never returns a
    silently-dropped or rewritten value.
    """
    if not provided:
        return {}

    profile = get_profile(b14_id)
    validated: dict[str, Any] = {}
    for name, value in provided.items():
        if name not in CANONICAL_OPTIONAL_FIELDS:
            raise _unsupported(b14_id, name, "알 수 없는 요청 옵션입니다.")
        if value is None:
            # Explicit null is treated as "not provided" and stays omitted.
            continue
        rule = profile.rule(name) if profile is not None else None
        if rule is None:
            raise _unsupported(
                b14_id,
                name,
                "이 모델의 공식 지원 근거가 확인되지 않았습니다(UNKNOWN).",
            )
        coercer = _COERCERS.get(rule.value_kind)
        if coercer is None:  # pragma: no cover - registry authoring guard
            raise _unsupported(b14_id, name, "지원 형식이 정의되지 않았습니다.")
        validated[name] = coercer(value, rule, b14_id)
    return validated


def build_upstream_parameters(
    b14_id: str, canonical: Mapping[str, Any]
) -> dict[str, Any]:
    """Map validated canonical fields onto the exact upstream JSON shape.

    Nested paths (e.g. ``chat_template_kwargs.enable_thinking``) are expanded.
    An unknown field is never invented: it is dropped only if it was not already
    validated by :func:`validate_optional_parameters`.
    """
    if not canonical:
        return {}
    profile = get_profile(b14_id)
    if profile is None:
        return {}
    upstream: dict[str, Any] = {}
    for name, value in canonical.items():
        rule = profile.rule(name)
        if rule is None:
            continue
        cursor = upstream
        for part in rule.upstream_path[:-1]:
            nested = cursor.get(part)
            if not isinstance(nested, dict):
                nested = {}
                cursor[part] = nested
            cursor = nested
        cursor[rule.upstream_path[-1]] = value
    return upstream


def describe_profile(b14_id: str) -> dict[str, Any]:
    """Emit the auditable per-model record required by the authority doc §8."""
    profile = get_profile(b14_id)
    if profile is None:
        return {
            "b14_id": b14_id,
            "profile_status": "UNKNOWN",
            "supported_optional_fields": [],
            "evidence_level": EVIDENCE_UNVERIFIED,
            "passthrough_test": "NOT_TESTED",
        }
    return {
        "b14_id": profile.b14_id,
        "profile_status": "DOCUMENTED",
        "serving_provider_id": profile.serving_provider_id,
        "serving_api_origin": profile.serving_api_origin,
        "upstream_model": profile.upstream_model,
        "model_developer": profile.model_developer,
        "base_model_id": profile.base_model_id,
        "variant_kind": profile.variant_kind,
        "variant_evidence": profile.variant_evidence,
        "manufacturer_doc_url": profile.manufacturer_doc_url,
        "manufacturer_doc_checked_at": profile.manufacturer_doc_checked_at,
        "provider_doc_url": profile.provider_doc_url,
        "provider_doc_checked_at": profile.provider_doc_checked_at,
        "provider_authenticated_models_evidence": profile.provider_authenticated_models_evidence,
        "supported_optional_fields": list(profile.supported_optional_fields),
        "supported_request_fields": {
            rule.name: {
                "upstream_path": ".".join(rule.upstream_path),
                "kind": rule.value_kind,
                "allowed": list(rule.allowed),
                "minimum": rule.minimum,
                "maximum": rule.maximum,
                "evidence": rule.evidence,
            }
            for rule in profile.rules
        },
        "native_defaults": dict(profile.native_defaults),
        "max_input_context": profile.max_input_context,
        "model_max_output": profile.model_max_output,
        "serving_max_output": profile.serving_max_output,
        "request_budget_contract": profile.request_budget_contract,
        "b14_operational_request_token_ceiling": B14_OPERATIONAL_REQUEST_TOKEN_CEILING,
        "evidence_level": profile.evidence_level,
        "passthrough_test": profile.passthrough_test,
    }


def registered_profile_ids() -> tuple[str, ...]:
    return tuple(sorted(PROFILES))


def render_markdown() -> str:
    """Render the auditable per-model parameter record as Markdown.

    The generated document is checked into the repository and a regression test
    asserts it stays byte-identical to this function, so the documentation can
    never silently drift from the code.
    """
    lines: list[str] = []
    lines.append("# B14 등록 모델별 공식 파라미터 프로필 (#3977)")
    lines.append("")
    lines.append(
        "> 이 문서는 `apps/korean-ai-platform/app/pilot/model_parameter_profiles.py` "
        "에서 생성됩니다. 직접 편집하지 말고 소스를 수정한 뒤 재생성하십시오."
    )
    lines.append("")
    lines.append("```text")
    lines.append(f"PROFILE_SCHEMA_VERSION={PROFILE_SCHEMA_VERSION}")
    lines.append(
        "B14_OPERATIONAL_REQUEST_TOKEN_CEILING="
        f"{B14_OPERATIONAL_REQUEST_TOKEN_CEILING}"
    )
    lines.append("TRANSPORT_BASELINE=temperature,max_tokens")
    lines.append(
        "CANONICAL_OPTIONAL_FIELDS=" + ",".join(CANONICAL_OPTIONAL_FIELDS)
    )
    lines.append("UNSPECIFIED_PARAMETERS=OMITTED")
    lines.append("UNKNOWN_CAPABILITY=FAIL_CLOSED")
    lines.append("PASSTHROUGH_TEST=NOT_TESTED")
    lines.append("```")
    lines.append("")
    lines.append(
        "`temperature`와 `max_tokens`는 등록된 모든 OpenAI 호환 엔드포인트가 광고하는 "
        "전송 기본 필드다. 사용자가 지정하지 않으면 전송하지 않는다. 그 외 옵션은 "
        "아래 표에서 해당 exact 모델이 문서로 지원한다고 표기된 경우에만 전달된다."
    )
    lines.append("")
    lines.append("## 요약")
    lines.append("")
    lines.append(
        "| B14 exact ID | serving provider | upstream model | variant | "
        "지원 옵션 | 근거 수준 | passthrough |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for model_id in registered_profile_ids():
        profile = PROFILES[model_id]
        supported = ", ".join(profile.supported_optional_fields) or "—"
        lines.append(
            f"| `{profile.b14_id}` | `{profile.serving_provider_id}` | "
            f"`{profile.upstream_model}` | `{profile.variant_kind}` | {supported} | "
            f"`{profile.evidence_level}` | `{profile.passthrough_test}` |"
        )
    lines.append("")
    lines.append("## 모델별 상세")
    for model_id in registered_profile_ids():
        profile = PROFILES[model_id]
        lines.append("")
        lines.append(f"### `{profile.b14_id}`")
        lines.append("")
        lines.append("```text")
        lines.append(f"SERVING_PROVIDER_ID={profile.serving_provider_id}")
        lines.append(f"SERVING_API_ORIGIN={profile.serving_api_origin}")
        lines.append(f"UPSTREAM_MODEL_ID={profile.upstream_model}")
        lines.append(f"MODEL_DEVELOPER={profile.model_developer}")
        lines.append(
            "BASE_MODEL_ID=" + (profile.base_model_id or "UNKNOWN")
        )
        lines.append(f"VARIANT_CLASS={profile.variant_kind}")
        lines.append(f"VARIANT_EVIDENCE={profile.variant_evidence}")
        lines.append(
            "MANUFACTURER_OFFICIAL_DOC_URL="
            + (profile.manufacturer_doc_url or "UNKNOWN")
        )
        lines.append(
            "MANUFACTURER_DOC_CHECKED_AT="
            + (profile.manufacturer_doc_checked_at or "UNKNOWN")
        )
        lines.append(
            "PROVIDER_EXACT_MODEL_OFFICIAL_DOC_URL="
            + (profile.provider_doc_url or "UNKNOWN")
        )
        lines.append(
            "PROVIDER_DOC_CHECKED_AT="
            + (profile.provider_doc_checked_at or "UNKNOWN")
        )
        lines.append(
            "PROVIDER_AUTHENTICATED_MODELS_EVIDENCE="
            + profile.provider_authenticated_models_evidence
        )
        lines.append(
            "SUPPORTED_OPTIONAL_PARAMS="
            + (",".join(profile.supported_optional_fields) or "UNKNOWN")
        )
        lines.append(
            "RECOMMENDED_OR_NATIVE_DEFAULTS="
            + (
                ",".join(f"{k}={v}" for k, v in profile.native_defaults.items())
                or "UNKNOWN"
            )
        )
        lines.append(
            "MAX_INPUT_CONTEXT="
            + (str(profile.max_input_context) if profile.max_input_context else "UNKNOWN")
        )
        lines.append(
            "MODEL_MAX_OUTPUT="
            + (str(profile.model_max_output) if profile.model_max_output else "UNKNOWN")
        )
        lines.append(
            "SERVING_MAX_OUTPUT="
            + (str(profile.serving_max_output) if profile.serving_max_output else "UNKNOWN")
        )
        lines.append(
            "REQUEST_BUDGET_CONTRACT=" + profile.request_budget_contract
        )
        lines.append(f"EVIDENCE_LEVEL={profile.evidence_level}")
        lines.append(f"PARAMETER_PASSTHROUGH_TEST={profile.passthrough_test}")
        lines.append(f"STREAM_NONSTREAM_PARITY={profile.passthrough_test}")
        lines.append("```")
        if profile.rules:
            lines.append("")
            lines.append("| 요청 필드 | upstream path | 형식 | 허용값 | 근거 |")
            lines.append("|---|---|---|---|---|")
            for rule in profile.rules:
                allowed = ", ".join(rule.allowed)
                if not allowed:
                    if rule.minimum is not None or rule.maximum is not None:
                        allowed = f"{rule.minimum}..{rule.maximum}"
                    else:
                        allowed = "—"
                lines.append(
                    f"| `{rule.name}` | `{'.'.join(rule.upstream_path)}` | "
                    f"`{rule.value_kind}` | {allowed} | {rule.evidence} |"
                )
        else:
            lines.append("")
            lines.append(
                "문서로 확인된 추가 옵션이 없다(`PARAMETER_SUPPORT_UNKNOWN`). "
                "명시적 추가 옵션 요청은 422로 거부된다."
            )
    lines.append("")
    return "\n".join(lines)

