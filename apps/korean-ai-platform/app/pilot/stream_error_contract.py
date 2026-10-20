"""Shared public streaming error contract for the Business 14 SSE surfaces.

The manual ``stream-preview`` surface and the staged ``auto-stream-preview``
surface both turn a provider or stream failure into a public HTTP status plus a
public message.  One table owns that mapping so the two surfaces cannot drift
into two different answers for the same condition, and so no surface can
publish provider-specific or upstream detail (an upstream HTTP status, a byte
budget, or a provider quota text) in a public body.

The status stays with the raiser, which owns the HTTP semantics of the
condition it raised.  The message comes from this table for every known
provider/stream failure code.  A caller or configuration error keeps its own
message, because that message is already product-neutral and carries the
actionable request detail.
"""

from __future__ import annotations

from app.pilot.errors import PilotError


# code -> (public HTTP status, public message)
STREAM_ERROR_DETAILS: dict[str, tuple[int, str]] = {
    "upstream_auth_failed": (401, "Provider 인증에 실패했습니다."),
    "upstream_rate_limited": (429, "Provider rate limit에 도달했습니다. 잠시 후 다시 시도하십시오."),
    "upstream_rate_limited_busy": (429, "Provider가 일시적으로 바쁩니다. 잠시 후 다시 시도하십시오."),
    "kilo_free_rate_limited": (429, "Provider 무료 티어 rate limit에 도달했습니다. 잠시 후 다시 시도하십시오."),
    "upstream_timeout": (504, "Provider 요청 시간이 초과되었습니다. 나중에 다시 시도하십시오."),
    "upstream_server_error": (502, "Provider 서버 오류가 발생했습니다. 나중에 다시 시도하십시오."),
    "upstream_client_error": (502, "Provider가 요청을 거부했습니다."),
    "malformed_upstream_response": (502, "Provider 응답 형식이 올바르지 않습니다."),
    "upstream_response_too_large": (502, "Provider 응답이 허용된 크기를 초과하여 중단되었습니다."),
    "pilot_not_configured": (503, "Business 14 Provider 연결이 준비되지 않았습니다."),
    "no_safe_route": (503, "안전한 라우팅 경로를 찾을 수 없습니다."),
    "empty_stream_answer": (502, "Provider가 표시 가능한 답변을 반환하지 않았습니다."),
    "stream_ended_without_done": (502, "Provider 스트리밍 응답이 정상적으로 종료되지 않았습니다."),
    "stream_execution_error": (502, "Provider 스트리밍 실행에 실패했습니다."),
}

# The public message used for a provider/stream failure code that this table
# does not know.  It never repeats the original failure detail.
DEFAULT_STREAM_ERROR_MESSAGE = "Provider 스트리밍 응답을 안전하게 완료하지 못했습니다."


def safe_stream_error_details(code: str) -> tuple[int, str]:
    """Public (status, message) for one provider/stream failure code."""
    return STREAM_ERROR_DETAILS.get(code, (502, DEFAULT_STREAM_ERROR_MESSAGE))


def pilot_error_from_code(code: str) -> PilotError:
    """Build the bounded public error for one provider/stream failure code."""
    status_code, message = safe_stream_error_details(code)
    return PilotError(code=code, message=message, status_code=status_code)


def public_stream_error(exc: PilotError) -> tuple[str, int, str]:
    """Public (code, status, message) for one stream failure.

    The status stays with the raiser.  The message comes from the shared table
    for every known provider/stream failure code, so neither SSE surface can
    publish provider-specific or upstream detail.  A caller or configuration
    error keeps its own message.
    """
    details = STREAM_ERROR_DETAILS.get(exc.code)
    if details is None:
        return exc.code, exc.status_code, exc.message
    return exc.code, exc.status_code, details[1]


__all__ = [
    "DEFAULT_STREAM_ERROR_MESSAGE",
    "STREAM_ERROR_DETAILS",
    "pilot_error_from_code",
    "public_stream_error",
    "safe_stream_error_details",
]
