from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .attachments import AttachmentValidationError, ImageAttachment, parse_attachments
from .history import validate_conversation_id, validate_project_id
from .model_policy import ModelPolicyError, resolve_model_policy
from .task_modes import TaskMode, get_task_mode
from .tool_presentations import ToolPresentationDescriptor, get_tool_presentation
from .web_tools import MAX_QUERY_CHARS, normalize_public_url

MAX_BROWSER_BODY_BYTES = 6_000_000
MAX_MESSAGES = 20
MAX_MESSAGE_CHARS = 8_000
MAX_TOTAL_MESSAGE_CHARS = 32_000
_ALLOWED_ROLES = {"user", "assistant"}


class BrowserRequestError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BrowserToolRequest:
    tool: ToolPresentationDescriptor
    tool_input: str | None


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
        if not query or len(query) > MAX_QUERY_CHARS:
            raise BrowserRequestError("검색어는 1자 이상 2000자 이하로 입력해 주세요.")
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


def _validate_payload(
    raw: Any,
) -> tuple[list[dict[str, str]], TaskMode, BrowserToolRequest | None, tuple[Any, ...], str | None, str | None]:
    if not isinstance(raw, dict):
        raise BrowserRequestError("요청 형식이 올바르지 않습니다.")
    if set(raw) - {"messages", "mode", "skill", "tool", "tool_input", "attachments", "conversation_id", "project_id"}:
        raise BrowserRequestError("지원하지 않는 요청 항목이 있습니다.")
    if raw.get("mode", "auto") != "auto":
        raise BrowserRequestError("현재는 자동 추천 모드만 지원합니다.")

    skill_id = raw.get("skill", "auto")
    if not isinstance(skill_id, str) or not skill_id.strip():
        raise BrowserRequestError("작업 모드 형식이 올바르지 않습니다.")
    try:
        skill = get_task_mode(skill_id.strip())
    except ValueError as exc:
        raise BrowserRequestError(str(exc)) from exc

    messages = raw.get("messages")
    if not isinstance(messages, list) or not 1 <= len(messages) <= MAX_MESSAGES:
        raise BrowserRequestError("대화 내용은 1개 이상 20개 이하로 보내 주세요.")
    out: list[dict[str, str]] = []
    total = 0
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
        if len(text) > MAX_MESSAGE_CHARS:
            raise BrowserRequestError("한 메시지가 너무 깁니다.")
        total += len(text)
        if total > MAX_TOTAL_MESSAGE_CHARS:
            raise BrowserRequestError("한 번에 보낸 대화가 너무 깁니다.")
        out.append({"role": role, "content": text})
    if not any(item["role"] == "user" for item in out):
        raise BrowserRequestError("사용자 질문이 필요합니다.")

    tool_request = _validate_tool_request(raw)
    try:
        attachments = parse_attachments(raw.get("attachments"))
    except AttachmentValidationError as exc:
        raise BrowserRequestError(str(exc)) from exc
    if tool_request is not None and any(isinstance(item, ImageAttachment) for item in attachments):
        raise BrowserRequestError("현재는 사진 첨부와 웹 도구를 한 요청에서 함께 사용할 수 없습니다.")
    try:
        conversation_id = validate_conversation_id(raw.get("conversation_id"))
        project_id = validate_project_id(raw.get("project_id"))
    except ValueError as exc:
        raise BrowserRequestError(str(exc)) from exc
    return out, skill, tool_request, attachments, conversation_id, project_id


def _apply_b62_model_policy(messages: list[dict[str, str]]) -> tuple[str, list[dict[str, str]]]:
    try:
        policy = resolve_model_policy(messages)
    except ModelPolicyError as exc:
        raise BrowserRequestError(exc.message) from exc
    return policy.model_id, policy.messages
