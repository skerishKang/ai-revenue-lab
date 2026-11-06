"""Signed app AI ingress on the COM2 Chat host; execution stays in P01/B14.

The signature is BookAI records v1: METHOD\\nPATH\\nTIMESTAMP\\nSUBJECT\\nSHA256(BODY).
Only the two server-owned subjects select policies and credentials. No browser
session, provider key or client-provided application identity authorizes a call.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any, Mapping

import httpx
from starlette.responses import JSONResponse
from starlette.routing import Route

from padiem_ai_engine_client import (
    ENGINE_EXECUTE_PATH, PadiemAiEngineClient, PadiemAiEngineClientError,
)
from .local_engine_transport import (
    LocalEngineHttpTransport, LocalEngineTransportError, MAX_ENGINE_REQUEST_BYTES,
)
from .local_p01_engine import local_p01_engine_config_from_env
from .com2_hmac import signature_matches, signature_time_error

APPS_AI_PATH = "/api/apps/ai"
POLICY_ENV = "PADIEM_APPS_AI_POLICY_JSON"
# Finish before the Pages caller (60s) and front proxy (65s) budgets.
APPS_AI_TIMEOUT_SECONDS = 55.0
DEFAULT_MODEL = "google/gemini-3.1-flash-lite"
_SUBJECTS = {
    "sub_app_storymemory": ("storymemory", "STORYMEMORY_COM2_AI_SECRET"),
    "sub_app_bookai": ("bookai", "BOOKAI_COM2_AI_SECRET"),
}
_THOUGHT = re.compile(r"<(/?)thought\b[^>]*>", re.IGNORECASE)


@dataclass(frozen=True)
class AppAIPolicy:
    name: str
    subject: str
    secret_name: str
    allowed_models: tuple[str, ...] = (DEFAULT_MODEL,)
    max_tokens: int = 900
    max_body_bytes: int = MAX_ENGINE_REQUEST_BYTES


def policies_from_env(env: Mapping[str, Any]) -> dict[str, AppAIPolicy]:
    raw = env.get(POLICY_ENV, "")
    try:
        settings = json.loads(raw) if raw else {}
        if not isinstance(settings, dict) or set(settings) - {"storymemory", "bookai"}:
            raise ValueError
        policies = {}
        for subject, (name, secret_name) in _SUBJECTS.items():
            item = settings.get(name, {})
            if not isinstance(item, dict) or set(item) - {"allowed_models", "max_tokens", "max_body_bytes"}:
                raise ValueError
            models = item.get("allowed_models", [DEFAULT_MODEL])
            tokens = item.get("max_tokens", 4096 if name == "bookai" else 900)
            limit = item.get("max_body_bytes", MAX_ENGINE_REQUEST_BYTES)
            if not isinstance(models, list) or not models or any(
                not isinstance(model, str) or not model.strip() or model != model.strip()
                for model in models
            ):
                raise ValueError
            if type(tokens) is not int or tokens < 1:
                raise ValueError
            if type(limit) is not int or not 1 <= limit <= MAX_ENGINE_REQUEST_BYTES:
                raise ValueError
            policies[subject] = AppAIPolicy(name, subject, secret_name, tuple(models), tokens, limit)
        return policies
    except (TypeError, ValueError):
        raise ValueError("apps_ai_policy_invalid") from None


class AppsAIEngineTransport(LocalEngineHttpTransport):
    """Reuse the host transport, adding execute only for this closed app lane."""

    def __init__(self, origin: str, *, app_name: str, client: httpx.AsyncClient | None = None):
        if app_name not in {"storymemory", "bookai"}:
            raise ValueError("invalid_apps_ai_name")
        super().__init__(origin, client=client, timeout=APPS_AI_TIMEOUT_SECONDS)
        self._app_name = app_name

    def _validated(self, **kwargs):
        extra = kwargs.pop("extra_paths", frozenset())
        path, method, headers = super()._validated(
            **kwargs, extra_paths=extra | frozenset({ENGINE_EXECUTE_PATH})
        )
        # Set by the HMAC-authenticated policy, never copied from the HTTP client.
        headers["x-padiem-client-app"] = self._app_name
        return path, method, headers


def strip_thought_blocks_reported(value: str) -> tuple[str, bool]:
    """The visible text plus whether an open block ran to the end of the answer.

    When depth is still open at the end, everything after the last tag was
    dropped with the block. That is an incomplete answer, not a shorter one.
    """
    output, depth, pos = [], 0, 0
    for match in _THOUGHT.finditer(value):
        if depth == 0:
            output.append(value[pos:match.start()])
        if match.group(1):
            depth = max(0, depth - 1)
        else:
            depth += 1
        pos = match.end()
    if depth == 0:
        output.append(value[pos:])
        return "".join(output).strip(), False
    return "".join(output).strip(), len(value) - pos > 0


def strip_thought_blocks(value: str) -> str:
    return strip_thought_blocks_reported(value)[0]


def _answer_truncation_reason(payload: Mapping[str, Any], visible: str, cut_here: bool,
                              budget_tokens: int) -> str | None:
    """Why the answer is not the whole answer. None means it is complete."""
    if cut_here or payload.get("answer_truncated") is True:
        return "thought_unclosed"
    usage = (payload.get("metadata") or {}).get("usage") if isinstance(payload.get("metadata"), Mapping) else None
    produced = usage.get("output_tokens") if isinstance(usage, Mapping) else None
    if type(produced) is int and type(budget_tokens) is int and budget_tokens >= 1 and produced >= budget_tokens:
        return "length_cap"
    return None


def _journal_answer_incomplete(name: str, reason: str, visible: str, payload: Mapping[str, Any]) -> None:
    """One bounded journal line. Never the answer text, the model or the provider."""
    usage = (payload.get("metadata") or {}).get("usage") if isinstance(payload.get("metadata"), Mapping) else None
    produced = usage.get("output_tokens") if isinstance(usage, Mapping) else "none"
    trace = payload.get("metadata", {}).get("trace_id") if isinstance(payload.get("metadata"), Mapping) else "none"
    print("app_ai_answer_incomplete app=%s reason=%s visible_chars=%d output_tokens=%s trace_id=%s"
          % (name, reason, len(visible), produced, trace), flush=True)


def _server_timing(started: float, p01_ms: float | None, engine_ms: int | None) -> str:
    """Elapsed split for one app AI request. Durations only, never a name.

    ``engine`` is the run duration P01 already reports in its response metadata;
    the exact B14 call time stays in the P01 journal and the B14 ledger.
    """
    def whole(value: float) -> int:
        return max(0, min(600_000, int(round(value))))

    parts = [f"chat;dur={whole(time.perf_counter() - started)}"]
    if p01_ms is not None:
        parts.append(f"p01;dur={whole(p01_ms)}")
    if engine_ms is not None:
        parts.append(f"engine;dur={whole(engine_ms)}")
    return ", ".join(parts)


def _error(code: str, status: int, retryable: bool | None = None) -> JSONResponse:
    error: dict[str, Any] = {"code": code}
    if retryable is not None:
        error["retryable"] = bool(retryable)
    return JSONResponse(
        {"ok": False, "error": error},
        status_code=status, headers={"cache-control": "no-store"},
    )


class AppsAIService:
    def __init__(self, env: Mapping[str, Any], *, client: httpx.AsyncClient | None = None, clock=time.time):
        self.policies = policies_from_env(env)
        self._clock = clock
        self._secrets = {
            subject: env.get(policy.secret_name, "")
            for subject, policy in self.policies.items()
        }
        self._engines = {}
        config, _diagnostic = local_p01_engine_config_from_env(env)
        if config is not None:
            for subject, policy in self.policies.items():
                self._engines[subject] = PadiemAiEngineClient(
                    transport=AppsAIEngineTransport(config.origin, app_name=policy.name, client=client),
                    app_id="b61", caller_id=config.caller_id, credential=config.credential,
                )

    async def handle(self, request):
        started = time.perf_counter()
        timing: dict[str, float | int] = {}
        response = await self._handle(request, timing)
        response.headers["Server-Timing"] = _server_timing(
            started, timing.get("p01"), timing.get("engine"),
        )
        return response

    async def _handle(self, request, timing: dict[str, float | int]):
        if request.method != "POST":
            return _error("method_not_allowed", 405)
        if request.url.path != APPS_AI_PATH or request.url.query:
            return _error("invalid_request", 400)
        # Service HMAC is the sole authorization on this endpoint.
        subject = request.headers.get("x-bookai-subject", "")
        policy = self.policies.get(subject)
        if policy is None:
            return _error("app_not_authorized", 403)
        secret = self._secrets.get(subject)
        if not isinstance(secret, str) or not secret:
            return _error("apps_ai_not_configured", 503)
        timestamp = request.headers.get("x-bookai-timestamp", "")
        signature = request.headers.get("x-bookai-signature", "")
        error = signature_time_error(timestamp, signature, now=self._clock())
        if error:
            return _error(error, 401)
        if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
            return _error("unsupported_media_type", 415)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > policy.max_body_bytes:
                return _error("request_too_large", 413)
        if not signature_matches(secret=secret, method="POST", path=APPS_AI_PATH,
                                 timestamp=timestamp, subject=subject, body=body, signature=signature):
            return _error("invalid_app_signature", 401)
        try:
            payload = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return _error("invalid_json", 400)
        if not isinstance(payload, dict) or payload.get("app_id") != "b61":
            return _error("app_not_authorized", 403)
        agent = payload.get("agent")
        if not isinstance(agent, dict):
            return _error("invalid_request", 400)
        model_policy = agent.get("model_policy")
        if not isinstance(model_policy, dict) or set(model_policy) != {"model", "max_retries"}:
            return _error("invalid_model_policy", 422)
        if model_policy.get("model") not in policy.allowed_models:
            return _error("model_not_allowed", 403)
        if type(model_policy.get("max_retries")) is not int or model_policy["max_retries"] != 0:
            return _error("model_retries_not_allowed", 422)
        tokens = agent.get("max_tokens")
        if type(tokens) is not int or not 1 <= tokens <= policy.max_tokens:
            return _error("app_token_limit_exceeded", 422)
        if payload.get("context_permission_required") is not True or not isinstance(payload.get("context_permission"), dict):
            return _error("context_permission_required", 422)
        engine = self._engines.get(subject)
        if engine is None:
            return _error("p01_not_configured", 503)
        try:
            p01_started = time.perf_counter()
            try:
                body = await engine.execute({key: value for key, value in payload.items() if key != "app_id"})
            finally:
                timing["p01"] = (time.perf_counter() - p01_started) * 1000.0
        except PadiemAiEngineClientError as error:
            status = error.status if isinstance(error.status, int) and 400 <= error.status <= 599 else 400
            if error.code in {"invalid_engine_response", "engine_http_error"} and status < 500:
                status = 502
            return _error(error.code, status)
        except (LocalEngineTransportError, httpx.HTTPError):
            return _error("p01_unavailable", 503)
        body = dict(body)
        metadata = body.get("metadata")
        duration_ms = metadata.get("duration_ms") if isinstance(metadata, Mapping) else None
        if type(duration_ms) is int and duration_ms >= 0:
            timing["engine"] = duration_ms
        visible, cut_here = strip_thought_blocks_reported(body["answer"])
        reason = _answer_truncation_reason(body, visible, cut_here, tokens)
        if reason is not None:
            # A half answer is not a success. The caller retries; it never sees
            # prose that stopped inside an unclosed block or at the budget.
            _journal_answer_incomplete(policy.name, reason, visible, body)
            return _error("answer_incomplete", 502, retryable=True)
        body["answer"] = visible
        return JSONResponse(body, headers={"cache-control": "no-store"})


def create_apps_ai_service(env, *, client=None, clock=time.time):
    return AppsAIService(env, client=client, clock=clock)


def install_apps_ai_routes(app, *, env, client=None):
    service = create_apps_ai_service(env, client=client)
    app.state.apps_ai_service = service
    app.router.routes.insert(0, Route(APPS_AI_PATH, service.handle, methods=["POST"]))
    return service
