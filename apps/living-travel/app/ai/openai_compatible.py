"""OpenAI-compatible structured-generation provider for Living Travel."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.request
from typing import Callable, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.domain.enums import CostClass, ProviderErrorCategory
from app.domain.models import ProviderResult


# ---------------------------------------------------------------------------
# Custom exception types for transport normalization
# ---------------------------------------------------------------------------

class ProviderTimeoutError(Exception):
    """Raised when the provider request times out."""
    pass


class ProviderHTTPError(Exception):
    """Raised for HTTP 4xx/5xx responses from the provider."""

    def __init__(self, status_code: int, message: str = "") -> None:
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


class ProviderTransportError(Exception):
    """Raised for transport-level errors (network, DNS, TLS, etc.)."""
    pass


class ProviderResponseTooLargeError(Exception):
    """Raised when the provider response exceeds the size limit."""
    pass


MAX_RESPONSE_SIZE = 2 * 1024 * 1024


# ---------------------------------------------------------------------------
# Resolver protocol for DNS verification
# ---------------------------------------------------------------------------

@runtime_checkable
class Resolver(Protocol):
    def resolve(self, hostname: str) -> list[str]: ...


class DefaultResolver:
    def resolve(self, hostname: str) -> list[str]:
        try:
            results = socket.getaddrinfo(hostname, None)
            ips = set()
            for family, _, _, _, sockaddr in results:
                ip = sockaddr[0]
                ips.add(ip)
            return list(ips)
        except socket.gaierror:
            raise ProviderTransportError("destination resolution failed")


# ---------------------------------------------------------------------------
# Transport protocol and default implementation
# ---------------------------------------------------------------------------

@runtime_checkable
class Transport(Protocol):
    def request(
        self,
        url: str,
        data: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        """Execute the HTTP request."""
        ...


class UrllibTransport:
    def __init__(
        self,
        *,
        base_url: str = "",
        environment: str = "development",
        allow_http_for_localhost: bool = False,
        max_response_size: int = MAX_RESPONSE_SIZE,
        resolver: Resolver | None = None,
    ) -> None:
        self._base_url = base_url
        self._environment = environment
        self._allow_http_for_localhost = allow_http_for_localhost
        self._max_response_size = max_response_size
        self._resolver = resolver or DefaultResolver()

    def request(
        self,
        url: str,
        data: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")

        opener = urllib.request.build_opener(_NoRedirectHandler)

        try:
            scheme, host = self._extract_scheme_and_host(url)
            if host:
                self._validate_destination(scheme, host)

            with opener.open(request, timeout=timeout) as resp:
                body = resp.read(self._max_response_size + 1)
                if len(body) > self._max_response_size:
                    raise ProviderResponseTooLargeError("response too large")
                return resp.status, body
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                raise ProviderHTTPError(e.code, "redirect not allowed")
            raise ProviderHTTPError(e.code, "http error")
        except urllib.error.URLError as e:
            reason = e.reason
            if isinstance(reason, socket.timeout):
                raise ProviderTimeoutError("connection timed out") from e
            if isinstance(reason, TimeoutError):
                raise ProviderTimeoutError("timeout") from e
            if isinstance(reason, Exception) and "timed out" in str(reason).lower():
                raise ProviderTimeoutError("timeout") from e
            raise ProviderTransportError(str(reason)) from e
        except socket.timeout as e:
            raise ProviderTimeoutError("connection timed out") from e
        except TimeoutError as e:
            raise ProviderTimeoutError("timeout") from e
        except (ProviderTimeoutError, ProviderHTTPError, ProviderTransportError, ProviderResponseTooLargeError):
            raise
        except Exception as e:
            raise ProviderTransportError(str(e)) from e

    def _extract_scheme_and_host(self, url: str) -> tuple[str, str | None]:
        from urllib.parse import urlparse
        try:
            parts = urlparse(url)
            return parts.scheme.lower(), parts.hostname
        except Exception:
            return "", None

    def _validate_destination(self, scheme: str, hostname: str) -> None:
        if not hostname:
            raise ProviderTransportError("missing hostname")

        hostname_lower = hostname.lower()

        try:
            literal_ip = ipaddress.ip_address(hostname_lower)
            ips_to_check = [literal_ip]
        except ValueError:
            resolved_ips = self._resolver.resolve(hostname_lower)
            ips_to_check = [ipaddress.ip_address(ip) for ip in resolved_ips if ip]

        if not ips_to_check:
            raise ProviderTransportError("destination resolution failed")

        if self._environment in ("testing", "development"):
            if scheme == "http":
                is_localhost_host = hostname_lower in (
                    "localhost",
                    "localhost.localdomain",
                    "::1",
                )
                try:
                    literal_ip = ipaddress.ip_address(hostname_lower)
                    is_localhost_host = is_localhost_host or literal_ip.is_loopback
                except ValueError:
                    pass

                if not is_localhost_host:
                    raise ProviderTransportError("SSRF blocked")

                if not all(ip.is_loopback for ip in ips_to_check):
                    raise ProviderTransportError("SSRF blocked")
                return

            if scheme == "https":
                for ip in ips_to_check:
                    if not ip.is_global:
                        raise ProviderTransportError("SSRF blocked")
                return

            raise ProviderTransportError("unsupported scheme")

        for ip in ips_to_check:
            if not ip.is_global:
                raise ProviderTransportError("destination is not a global address")


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

TASK_NAMES = frozenset({"editorial_plan", "edition_draft"})


def _make_correlation_id(request_id: str) -> str:
    hasher = hashlib.sha256(request_id.encode("utf-8"))
    return hasher.hexdigest()[:32]


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: int = 30,
        cost_class: CostClass = CostClass.free,
        transport: Transport | None = None,
        environment: str = "development",
        resolver: Resolver | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        # Use the final chat-completions URL directly.
        # URL normalization is handled by Settings.ai_chat_completions_url.
        # The provider does NOT re-normalize or modify the URL.
        self._chat_url = base_url

        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._cost_class = cost_class
        self._environment = environment
        self._monotonic = monotonic

        if transport is None:
            self._transport = UrllibTransport(
                base_url=base_url,
                environment=environment,
                resolver=resolver,
            )
        else:
            self._transport = transport

        self._provider_name = "openai_compatible"

    @property
    def attempt_limit(self) -> int:
        return 1

    @property
    def redacted_api_key(self) -> str:
        if len(self._api_key) > 8:
            return self._api_key[:4] + "..." + self._api_key[-4:]
        return "***"

    @property
    def source_allowlist_predicate(self) -> None:
        return None

    def generate_structured(
        self,
        *,
        task_name: str,
        system_prompt: str,
        user_payload: dict,
        response_schema: type[BaseModel],
        request_id: str,
    ) -> ProviderResult:
        start = self._monotonic()
        opaque_id = _make_correlation_id(request_id)

        if task_name not in TASK_NAMES:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=(self._monotonic() - start) * 1000,
                success=False,
                error_category=ProviderErrorCategory.unknown,
                error_message=f"unsupported task: {task_name}",
            )

        try:
            body = self._build_request_body(system_prompt, user_payload)
            status, raw = self._do_request(body, opaque_id)
        except TimeoutError:
            return self._fail_result(start, ProviderErrorCategory.timeout, "provider request timed out")
        except ProviderTimeoutError:
            return self._fail_result(start, ProviderErrorCategory.timeout, "provider request timed out")
        except ProviderResponseTooLargeError:
            return self._fail_result(start, ProviderErrorCategory.provider_error, "provider response too large")
        except ProviderHTTPError as e:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=(self._monotonic() - start) * 1000,
                success=False,
                error_category=ProviderErrorCategory.provider_error,
                error_message="provider http error",
            )
        except ProviderTransportError as e:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=(self._monotonic() - start) * 1000,
                success=False,
                error_category=ProviderErrorCategory.provider_error,
                error_message="provider request failed",
            )
        except Exception:
            return self._fail_result(start, ProviderErrorCategory.unknown, "unexpected error")

        latency_ms = (self._monotonic() - start) * 1000

        if status != 200:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=latency_ms,
                success=False,
                error_category=ProviderErrorCategory.provider_error,
                error_message=f"provider returned http {status}",
            )

        # Strict envelope validation
        if not isinstance(raw, bytes):
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "response is not bytes")

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "provider returned malformed JSON")

        if not isinstance(parsed, dict):
            return self._fail_result(start, ProviderErrorCategory.provider_error, "response is not a JSON object")

        usage = parsed.get("usage")
        if usage is not None and not isinstance(usage, dict):
            return self._fail_result(start, ProviderErrorCategory.provider_error, "usage is not a JSON object")

        prompt_tokens = 0
        completion_tokens = 0
        if isinstance(usage, dict):
            pt = usage.get("prompt_tokens")
            ct = usage.get("completion_tokens")
            # Strict validation: must be non-negative int (not bool, not float, not str)
            if pt is not None:
                if isinstance(pt, bool) or not isinstance(pt, int) or pt < 0:
                    return self._fail_result(start, ProviderErrorCategory.provider_error, "prompt_tokens is invalid")
                prompt_tokens = pt
            if ct is not None:
                if isinstance(ct, bool) or not isinstance(ct, int) or ct < 0:
                    return self._fail_result(start, ProviderErrorCategory.provider_error, "completion_tokens is invalid")
                completion_tokens = ct

        try:
            choices = parsed.get("choices")
        except (KeyError, TypeError, AttributeError):
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "provider response missing choices")

        if not isinstance(choices, list) or len(choices) == 0:
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "provider returned empty choices")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "first choice is not an object")

        message = first_choice.get("message")
        if not isinstance(message, dict):
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "message is not an object")

        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "content is not a non-empty string")

        content_stripped = content.strip()
        if content_stripped.startswith("```"):
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "provider returned fenced JSON")

        try:
            payload = json.loads(content_stripped)
        except (json.JSONDecodeError, ValueError):
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "provider content is not valid JSON")

        if not isinstance(payload, dict):
            return self._fail_result(start, ProviderErrorCategory.schema_mismatch, "provider returned array, expected object")

        try:
            validated = response_schema.model_validate(payload)
        except Exception:
            return self._fail_result(start, ProviderErrorCategory.schema_mismatch, "provider response failed schema validation")

        return ProviderResult(
            provider=self._provider_name,
            model=self._model,
            cost_class=self._cost_class,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            payload=validated.model_dump(),
            success=True,
        )

    def _fail_result(
        self,
        start: float,
        category: ProviderErrorCategory,
        message: str,
    ) -> ProviderResult:
        return ProviderResult(
            provider=self._provider_name,
            model=self._model,
            cost_class=self._cost_class,
            latency_ms=(self._monotonic() - start) * 1000,
            success=False,
            error_category=category,
            error_message=message,
        )

    def _build_request_body(self, system_prompt: str, user_payload: dict) -> bytes:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ]
        body = {
            "model": self._model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        return json.dumps(body, ensure_ascii=False).encode("utf-8")

    def _do_request(self, body: bytes, correlation_id: str) -> tuple[int, bytes]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "X-Request-ID": correlation_id,
        }
        return self._transport.request(
            self._chat_url,
            data=body,
            headers=headers,
            timeout=self._timeout,
        )