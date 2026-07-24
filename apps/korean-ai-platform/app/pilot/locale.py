"""Minimal i18n module for Business 14 (Korean-first, English optional).

Policy (docs/BUSINESS14_LANGUAGE_POLICY.md):
- Default: ko-KR
- Unknown/empty locale: ko-KR
- Invalid locale: ko-KR
- User explicitly selects 'en': English
- Missing English translation: Korean fallback
- Accept-Language header is ignored (user must explicitly choose)
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class Locale(str, Enum):
    KO = "ko-KR"
    EN = "en"


# Korean-first translation table.
# English fallback to Korean is done by gettext() returning the key's Korean
# value when English translation is absent.
_TRANSLATIONS: dict[str, dict[Locale, str]] = {}


def _t(key: str, ko: str, en: str | None = None) -> None:
    """Register a Korean (and optional English) translation."""
    _TRANSLATIONS[key] = {Locale.KO: ko}
    if en:
        _TRANSLATIONS[key][Locale.EN] = en


# ── Workspace ──────────────────────────────────────────────────────────
_t("workspace.title", "Workspace", "Workspace")
_t("workspace.heading", "AI 모델 대화", "AI Model Chat")
_t(
    "workspace.description",
    "Provider API key를 입력하고 모델을 선택해 대화를 시작하세요. "
    "key는 저장되지 않으며 페이지 새로고침 시 초기화됩니다.",
    "Enter your Provider API key, select a model, and start chatting. "
    "Your key is never stored and resets on page reload.",
)
_t("workspace.provider_count", "Provider 수", "Providers")
_t("workspace.model_count", "모델 수", "Models")
_t("workspace.select_model", "모델 선택", "Select Model")
_t("workspace.api_key", "Provider API Key", "Provider API Key")
_t("workspace.key_placeholder", "API key를 입력하세요...", "Enter your API key...")
_t("workspace.key_note", "입력한 key는 이 페이지 세션에서만 사용되며 저장하지 않습니다.", "Your key is used only for this page session and is not stored.")
_t("workspace.key_status_set", "현재 페이지에서만 사용 중", "Active for this page only")
_t("workspace.key_status_empty", "API key 없음", "No API key")
_t("workspace.key_apply", "API key 적용", "Apply API Key")
_t("workspace.key_clear", "API key 지우기", "Clear API Key")
_t("workspace.chat_placeholder", "메시지를 입력하세요...", "Type your message...")
_t("workspace.send", "보내기", "Send")
_t("workspace.sending", "전송 중...", "Sending...")
_t("workspace.new_chat", "새 대화", "New Chat")
_t("workspace.clear_chat", "대화 지우기", "Clear Chat")
_t("workspace.model_provider", "Provider", "Provider")
_t("workspace.cost_label", "예상 비용", "Estimated Cost")
_t("workspace.cost_unknown", "확인 불가", "Unknown")
_t(
    "workspace.cost_notice",
    "실제 사용료는 연결한 Provider 계정과 계약에 따라 별도로 청구됩니다. "
    "Business 14는 이 파일럿에서 사용료를 청구하지 않습니다.",
    "Actual usage fees are billed separately by your Provider contract. "
    "Business 14 does not charge for this pilot.",
)
_t("workspace.security_notice", "key를 저장하지 않습니다. 페이지 새로고침 시 대화와 key가 모두 초기화됩니다.", "Keys are not stored. Page reload clears both chat and key.")
_t("workspace.message_limit_warning", "메시지가 너무 많습니다. 새 대화를 시작하거나 메시지를 줄이십시오.", "Too many messages. Start a new chat or reduce messages.")
_t("workspace.request_id", "Request ID", "Request ID")
_t("workspace.latency", "지연 시간", "Latency")
_t("workspace.tokens", "토큰", "Tokens")
_t("workspace.pilot_notice", "Phase 3 Pilot입니다. 인증, 다중 사용자 격리, 결제, SLA가 구현된 상용 서비스가 아닙니다.", "Phase 3 Pilot. This is not a production service with auth, multi-tenant isolation, billing, or SLA.")
_t("workspace.provider_changed", "Provider가 변경되어 key와 대화가 초기화되었습니다. 새 API key를 입력하십시오.", "Provider changed. Key and conversation cleared. Enter a new API key.")
_t("workspace.model_changed", "모델이 변경되어 대화가 초기화되었습니다.", "Model changed. Conversation cleared.")
_t("workspace.empty_key", "API key가 설정되지 않았습니다.", "No API key set.")
_t("workspace.lang_switch", "English", "한국어")

# ── Errors (Korean) ─────────────────────────────────────────────────────
_t("error.registry_invalid", "Provider registry 설정이 올바르지 않습니다.", "Provider registry configuration is invalid.")
_t("error.model_not_found", "선택한 모델을 찾을 수 없습니다.", "Selected model not found.")
_t("error.model_disabled", "선택한 모델은 현재 비활성화되어 있습니다.", "Selected model is currently disabled.")
_t("error.missing_provider_key", "Provider API key가 필요합니다.", "Provider API key is required.")
_t("error.placeholder_key_rejected", "실제 Provider API key를 입력하십시오.", "Please enter a real Provider API key.")
_t("error.upstream_auth_failed", "Provider 인증에 실패했습니다. API key를 확인하십시오.", "Provider authentication failed. Check your API key.")
_t("error.upstream_rate_limited", "Provider rate limit에 도달했습니다. 잠시 후 다시 시도하십시오.", "Provider rate limit reached. Please try again later.")
_t("error.upstream_timeout", "Provider 요청 시간이 초과되었습니다.", "Provider request timed out.")
_t("error.upstream_server_error", "Provider 서버 오류가 발생했습니다.", "Provider server error.")
_t("error.malformed_upstream_response", "Provider 응답 형식이 올바르지 않습니다.", "Provider response format is invalid.")
_t("error.internal_error", "요청을 처리하는 중 내부 오류가 발생했습니다.", "An internal error occurred while processing your request.")
_t("error.pilot_not_configured", "Pilot이 설정되지 않았습니다.", "Pilot is not configured.")
_t("error.missing_prompt", "메시지를 입력하십시오.", "Please enter a message.")

# ── Nav / Common ────────────────────────────────────────────────────────
_t("nav.home", "대화하기", "Chat")
_t("nav.pilot", "BYOK Gateway", "BYOK Gateway")
_t("nav.models", "모델 카탈로그", "Models")
_t("nav.playground", "API Playground", "API Playground")
_t("nav.api_keys", "API 키", "API Keys")
_t("nav.usage", "사용량", "Usage")
_t("nav.docs", "API 문서", "API Docs")
_t("nav.pricing", "요금", "Pricing")
_t("nav.access", "이용 방식", "Access Modes")
_t("lang.switch", "English", "한국어")
_t("common.no_data", "데이터 없음", "No data")
_t("common.loading", "로딩 중...", "Loading...")
_t("common.close", "닫기", "Close")
_t("common.brand", "Korean AI Platform", "Korean AI Platform")


def gettext(key: str, locale: Locale = Locale.KO, **kwargs: Any) -> str:
    """Get translated text for the given key and locale.

    Falls back to Korean if English translation is missing.
    Falls back to key itself if no translation exists.
    Supports simple {placeholder} substitution via **kwargs.
    """
    entry = _TRANSLATIONS.get(key)
    if entry is None:
        return key

    text = entry.get(locale) or entry.get(Locale.KO, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except KeyError:
            return text
    return text


# ── Legacy shortcut for Korean-first pages ──────────────────────────────
_ = gettext  # Korean default


def locale_from_request(request) -> Locale:
    """Extract locale preference from request.

    Rules:
    1. lang query param exists:
       - en -> English
       - ko-KR -> Korean
       - anything else -> Korean (invalid query never falls back to cookie)
    2. No lang query param:
       - valid cookie -> use cookie
       - no cookie / invalid cookie -> Korean
    Accept-Language header is ignored — user must explicitly choose.
    """
    # Check if lang key EXISTS in query params
    if "lang" in request.query_params:
        q = request.query_params.get("lang", "")
        # Query present: use valid value or Korean for invalid/empty
        if q in (Locale.KO, Locale.EN):
            return Locale(q)
        return Locale.KO

    # No lang query: fall back to cookie
    c = request.cookies.get("locale_preference", "")
    if c in (Locale.KO, Locale.EN):
        return Locale(c)

    return Locale.KO


def set_locale_cookie(response, locale: Locale) -> None:
    """Set locale_preference cookie on the response."""
    response.set_cookie(
        key="locale_preference",
        value=locale.value,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=365 * 24 * 3600,
    )
