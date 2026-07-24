"""Normalized error types for the BYOK Gateway Pilot."""

from __future__ import annotations


class PilotError(Exception):
    """Base pilot error with a stable error code."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class PilotNotConfigured(PilotError):
    def __init__(self) -> None:
        super().__init__(
            code="pilot_not_configured",
            message="BYOK Gateway Pilot가 설정되지 않았습니다. 환경변수 BUSINESS14_PILOT_BASE_URL과 BUSINESS14_PILOT_MODEL_ID를 확인하십시오.",
            status_code=503,
        )


class MissingProviderKey(PilotError):
    def __init__(self) -> None:
        super().__init__(
            code="missing_provider_key",
            message="Provider API key가 필요합니다. X-Business14-Provider-Key 헤더에 실제 API key를 전달하십시오.",
            status_code=401,
        )


class PlaceholderKeyRejected(PilotError):
    def __init__(self) -> None:
        super().__init__(
            code="placeholder_key_rejected",
            message="Placeholder API key는 허용되지 않습니다. 실제 Provider API key를 X-Business14-Provider-Key 헤더에 전달하십시오.",
            status_code=401,
        )


class UnsupportedModel(PilotError):
    def __init__(self, model_id: str) -> None:
        super().__init__(
            code="unsupported_model",
            message=f"모델 '{model_id}'은(는) Pilot에서 지원하지 않습니다. GET /api/pilot/models에서 사용 가능한 모델을 확인하십시오.",
            status_code=400,
        )


class StreamNotSupported(PilotError):
    def __init__(self) -> None:
        super().__init__(
            code="stream_not_supported",
            message="스트리밍(stream=true)은 현재 Pilot에서 지원하지 않습니다. stream=false를 사용하십시오.",
            status_code=400,
        )


class ToolsNotSupported(PilotError):
    def __init__(self) -> None:
        super().__init__(
            code="tools_not_supported",
            message="tools/function calling은 현재 Pilot에서 지원하지 않습니다.",
            status_code=400,
        )


class UpstreamAuthFailed(PilotError):
    def __init__(self) -> None:
        super().__init__(
            code="upstream_auth_failed",
            message="Provider 인증에 실패했습니다. X-Business14-Provider-Key 헤더의 API key를 확인하십시오.",
            status_code=401,
        )


class UpstreamRateLimited(PilotError):
    def __init__(self) -> None:
        super().__init__(
            code="upstream_rate_limited",
            message="Provider rate limit에 도달했습니다. 잠시 후 다시 시도하십시오.",
            status_code=429,
        )


class UpstreamTimeout(PilotError):
    def __init__(self) -> None:
        super().__init__(
            code="upstream_timeout",
            message="Provider 요청 시간이 초과되었습니다. 나중에 다시 시도하십시오.",
            status_code=504,
        )


class UpstreamServerError(PilotError):
    def __init__(self) -> None:
        super().__init__(
            code="upstream_server_error",
            message="Provider 서버 오류가 발생했습니다. 나중에 다시 시도하십시오.",
            status_code=502,
        )


class MalformedUpstreamResponse(PilotError):
    def __init__(self) -> None:
        super().__init__(
            code="malformed_upstream_response",
            message="Provider 응답 형식이 올바르지 않습니다.",
            status_code=502,
        )


class InvalidRequest(PilotError):
    def __init__(self, detail: str = "요청 형식이 올바르지 않습니다.") -> None:
        super().__init__(
            code="invalid_request",
            message=detail,
            status_code=400,
        )
