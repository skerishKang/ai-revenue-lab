from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .attachments import (
    AttachmentValidationError,
    ImageAttachment,
    parse_attachments,
    parse_attachments_async,
)
from .history import (
    validate_chat_pc_run_id,
    validate_conversation_id,
    validate_project_id,
)
from .model_policy import ModelPolicyError, resolve_model_policy, resolve_tier_policy
from .task_modes import TaskMode, get_task_mode
from .tool_presentations import ToolPresentationDescriptor, get_tool_presentation
from .web_tools import MAX_QUERY_CHARS, SEARCH_QUERY_TOO_LONG_MESSAGE, normalize_public_url

# #4379: a browser request body carries no PADIEM byte total. The reader
# stays incremental, so the body is never materialized past the platform's
# own request limit. The main branch raised this constant to a very large
# finite value; a finite value is still a PADIEM total, so the limit is
# removed instead of enlarged.
MAX_BROWSER_BODY_BYTES: int | None = None
_ALLOWED_ROLES = {"user", "assistant"}
# Routing label for the three 의원3종 utilities. It grants no identity, tier,
# entitlement or tool scope, and it is not an authentication input.
_UTIL_SCOPES = frozenset({"speech", "sns", "meeting"})
# #6046: content country for the three 의원3종 utilities. Like `util` this is a
# presentation/routing label — it selects the output language and wording and
# grants no identity, tier, entitlement, legal jurisdiction or storage region.
COUNTRIES = frozenset({"kr", "us", "uk", "fr"})
DEFAULT_COUNTRY = "kr"


class BrowserRequestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BrowserToolRequest:
    tool: ToolPresentationDescriptor
    tool_input: str | None


@dataclass(frozen=True, slots=True)
class CustomModelSelection:
    """Explicit PADIEM Custom provider/model choice (never inferred)."""

    provider: str
    model: str


def parse_custom_selection(value: Any) -> CustomModelSelection:
    """Validate one explicit PADIEM Custom selection shared by every product."""
    if not isinstance(value, dict) or set(value) != {"provider", "model"}:
        raise BrowserRequestError("PADIEM Custom 선택 형식이 올바르지 않습니다.")
    provider = value.get("provider")
    model = value.get("model")
    if (not isinstance(provider, str) or not provider.strip()
            or not isinstance(model, str) or not model.strip()):
        raise BrowserRequestError("PADIEM Custom 선택 형식이 올바르지 않습니다.")
    return CustomModelSelection(provider=provider.strip(), model=model.strip())


def _validate_custom_selection(raw: dict[str, Any]) -> CustomModelSelection | None:
    if "custom" not in raw:
        return None
    custom = parse_custom_selection(raw.get("custom"))
    if "tier" in raw:
        raise BrowserRequestError(
            "PADIEM 제공 모델과 PADIEM Custom을 한 요청에서 함께 선택할 수 없습니다."
        )
    return custom


def _validate_tool_request(raw: dict[str, Any]) -> BrowserToolRequest | None:
    tool_value = raw.get("tool")
    has_tool_input = "tool_input" in raw
    if tool_value is None:
        if has_tool_input:
            raise BrowserRequestError("도구 입력을 사용하려면 도구를 함께 선택해 주세요.")
        return None
    if not isinstance(tool_value, str) or not tool_value.strip():
        raise BrowserRequestError("도구 형식이 올바르지 않습니다.")
    try:
        tool = get_tool_presentation(tool_value.strip())
    except ValueError as exc:
        raise BrowserRequestError(str(exc)) from exc

    value = raw.get("tool_input")
    if tool.id in {"web_search", "deep_research"}:
        if value is None:
            return BrowserToolRequest(tool=tool, tool_input=None)
        if not isinstance(value, str):
            raise BrowserRequestError("검색어 형식이 올바르지 않습니다.")
        query = value.strip()
        if not query:
            raise BrowserRequestError("검색할 내용을 한 줄로 알려 주세요.")
        if len(query) > MAX_QUERY_CHARS:
            # #6090: MAX_QUERY_CHARS is the search provider's own query contract.
            # The answer names what the user can do, not the number.
            raise BrowserRequestError(SEARCH_QUERY_TOO_LONG_MESSAGE)
        return BrowserToolRequest(tool=tool, tool_input=query)
    if tool.id == "web_fetch":
        if not isinstance(value, str) or not value.strip():
            raise BrowserRequestError("읽을 공개 웹 주소가 필요합니다.")
        try:
            safe_url = normalize_public_url(value)
        except ValueError as exc:
            raise BrowserRequestError(str(exc)) from exc
        return BrowserToolRequest(tool=tool, tool_input=safe_url)
    raise BrowserRequestError("지원하지 않는 도구입니다.")


def declared_util_scope(raw: Any) -> str | None:
    """Return the utility scope of a request that declared one.

    Call this only after ``_validate_payload_async`` accepted the payload; the
    re-check here is the trust boundary, not a second validator.
    """
    scope = raw.get("util") if isinstance(raw, dict) else None
    return scope if isinstance(scope, str) and scope in _UTIL_SCOPES else None


def declared_country(raw: Any) -> str:
    """Content country of a request. Absent means kr, so every existing client
    keeps today's Korean behaviour without sending anything new."""
    value = raw.get("country") if isinstance(raw, dict) else None
    return value if isinstance(value, str) and value in COUNTRIES else DEFAULT_COUNTRY


def _validate_payload_parts(
    raw: Any,
) -> tuple[list[dict[str, str]], TaskMode, BrowserToolRequest | None]:
    if not isinstance(raw, dict):
        raise BrowserRequestError("요청 형식이 올바르지 않습니다.")
    # `mode` is gone, not merely unvalidated: B14 automatic model selection was
    # abolished (#4844), the server accepted only "auto", and the four-mode catalog
    # in `app/chat_modes.py` (자동/빠르게/균형/깊게) had no call site at all. A key that
    # no client may meaningfully set is refused here rather than ignored, so nothing
    # can grow a mode-shaped promise again.
    # The tail order below is a load-bearing literal: test_5015 pins
    # `"pc_run_id", "web_search"}` as the end of this set.
    if set(raw) - {"messages", "tier", "skill", "tool", "tool_input", "attachments", "conversation_id", "project_id", "timezone", "calendar_turn_id", "custom", "device_id", "util", "country", "pc_run_id", "web_search"}:
        raise BrowserRequestError("지원하지 않는 요청 항목이 있습니다.")
    if "util" in raw:
        util_scope = raw["util"]
        if not isinstance(util_scope, str) or util_scope not in _UTIL_SCOPES:
            raise BrowserRequestError("유틸 업무 식별자가 올바르지 않습니다.")
    if "country" in raw:
        country = raw["country"]
        if not isinstance(country, str) or country not in COUNTRIES:
            raise BrowserRequestError("국가 식별자가 올바르지 않습니다.")
    if "pc_run_id" in raw:
        try:
            validate_chat_pc_run_id(raw.get("pc_run_id"))
        except ValueError as exc:
            raise BrowserRequestError("PC 작업 실행 ID가 올바르지 않습니다.") from exc
    if "calendar_turn_id" in raw:
        turn_id = raw["calendar_turn_id"]
        if not isinstance(turn_id, str) or not turn_id.strip() or len(turn_id) > 128:
            raise BrowserRequestError("Calendar 요청 식별자 형식이 올바르지 않습니다.")

    skill_id = raw.get("skill", "auto")
    if not isinstance(skill_id, str) or not skill_id.strip():
        raise BrowserRequestError("작업 모드 형식이 올바르지 않습니다.")
    try:
        skill = get_task_mode(skill_id.strip())
    except ValueError as exc:
        raise BrowserRequestError(str(exc)) from exc

    messages = raw.get("messages")
    if not isinstance(messages, list) or not messages:
        raise BrowserRequestError("대화 내용은 1개 이상 보내 주세요.")
    out: list[dict[str, str]] = []
    for item in messages:
        if not isinstance(item, dict) or set(item) != {"role", "content"}:
            raise BrowserRequestError("대화 항목 형식이 올바르지 않습니다.")
        role = item.get("role")
        content = item.get("content")
        if role not in _ALLOWED_ROLES:
            raise BrowserRequestError("브라우저에서는 사용자와 AI 대화만 보낼 수 있습니다.")
        if not isinstance(content, str) or not content.strip():
            raise BrowserRequestError("빈 메시지는 보낼 수 없습니다.")
        text = content.strip()
        out.append({"role": role, "content": text})
    if not any(item["role"] == "user" for item in out):
        raise BrowserRequestError("사용자 질문이 필요합니다.")

    tool_request = _validate_tool_request(raw)
    return out, skill, tool_request


def _finish_payload(
    raw: dict[str, Any],
    *,
    messages: list[dict[str, str]],
    skill: TaskMode,
    tool_request: BrowserToolRequest | None,
    attachments: tuple[Any, ...],
) -> tuple[list[dict[str, str]], TaskMode, BrowserToolRequest | None, tuple[Any, ...], str | None, str | None, CustomModelSelection | None]:
    if tool_request is not None and any(isinstance(item, ImageAttachment) for item in attachments):
        raise BrowserRequestError("현재는 사진 첨부와 웹 도구를 한 요청에서 함께 사용할 수 없습니다.")
    custom = _validate_custom_selection(raw)
    if custom is not None and (tool_request is not None or attachments):
        raise BrowserRequestError("PADIEM Custom은 현재 텍스트 대화만 지원합니다.")
    try:
        conversation_id = validate_conversation_id(raw.get("conversation_id"))
        project_id = validate_project_id(raw.get("project_id"))
    except ValueError as exc:
        raise BrowserRequestError(str(exc)) from exc
    return messages, skill, tool_request, attachments, conversation_id, project_id, custom


def _validate_payload(
    raw: Any,
) -> tuple[list[dict[str, str]], TaskMode, BrowserToolRequest | None, tuple[Any, ...], str | None, str | None, CustomModelSelection | None]:
    messages, skill, tool_request = _validate_payload_parts(raw)
    try:
        attachments = parse_attachments(raw.get("attachments"))
    except AttachmentValidationError as exc:
        raise BrowserRequestError(str(exc)) from exc
    return _finish_payload(
        raw,
        messages=messages,
        skill=skill,
        tool_request=tool_request,
        attachments=attachments,
    )


async def _validate_payload_async(
    raw: Any, *, file_resolver=None,
) -> tuple[list[dict[str, str]], TaskMode, BrowserToolRequest | None, tuple[Any, ...], str | None, str | None, CustomModelSelection | None]:
    """Worker request path: validate with the async isolated parser authority."""

    messages, skill, tool_request = _validate_payload_parts(raw)
    try:
        attachments = await parse_attachments_async(raw.get("attachments"), file_resolver=file_resolver)
    except AttachmentValidationError as exc:
        raise BrowserRequestError(str(exc)) from exc
    return _finish_payload(
        raw,
        messages=messages,
        skill=skill,
        tool_request=tool_request,
        attachments=attachments,
    )


def _apply_b62_model_policy(
    messages: list[dict[str, str]],
    *,
    tier_id: str | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """Resolve browser tier selection without exposing provider/model authority.

    Explicit browser tier ids are resolved server-side through the shared Padiem
    product-tier contract. With no tier field, hidden slash aliases remain a
    compatibility/test surface.
    """
    try:
        if tier_id is None:
            policy = resolve_model_policy(messages, require_executable=False)
        else:
            # Browser validation owns product identity only. Executability is
            # enforced by B14Client/P01 at the dispatch boundary so mock,
            # projects and other non-model features remain usable while a tier
            # is deliberately HOLD (#3568).
            policy = resolve_tier_policy(messages, tier_id, require_executable=False)
    except ModelPolicyError as exc:
        raise BrowserRequestError(exc.message) from exc
    # Preserve validated browser messages until the B14/tier-identity dispatch
    # boundary. Hidden slash selectors are stripped by the existing client-side
    # model policy there; explicit browser tier selection rides request context.
    return policy.model_id, [dict(message) for message in messages]
