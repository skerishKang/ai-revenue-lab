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
# Transport protocol and default implementation
# ---------------------------------------------------------------------------

@runtime_checkable
class Transport(Protocol):
    """Injectable HTTP transport for the provider.

    Default implementation uses ``urllib.request`` with redirect blocking
    and SSRF protections.  Tests inject a stub that returns synthetic
    responses without opening a real socket.
    """

    def request(
        self,
        url: str,
        data: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        """Execute the HTTP request.

        Returns
        -------
        tuple[int, bytes]
            HTTP status code and response body bytes.

        Raises
        ------
        ProviderTimeoutError, ProviderHTTPError, ProviderTransportError,
        ProviderResponseTooLargeError
        """
        ...


class UrllibTransport:
    """Default transport backed by ``urllib.request`` (stdlib, no extra dep).

    Features
    --------
    - Redirect blocking (301, 302, 303, 307, 308 follow disabled)
    - SSRF protection via ipaddress module
    - Response size limit (2 MiB max)
    - Custom exception normalization
    """

    def __init__(
        self,
        *,
        environment: str = "development",
        allow_http_for_localhost: bool = True,
        max_response_size: int = MAX_RESPONSE_SIZE,
    ) -> None:
        self._environment = environment
        self._allow_http_for_localhost = allow_http_for_localhost
        self._max_response_size = max_response_size

    def request(
        self,
        url: str,
        data: bytes,
        headers: dict[str, str],
        timeout: float,
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")

        opener = urllib.request.build_opener(_NoRedirectHandler)
        urllib.request.install_opener(opener)

        try:
            # SSRF validation before request
            host = self._extract_host(url)
            if host:
                self._validate_destination(host)

            with opener.open(request, timeout=timeout) as resp:
                body = resp.read(self._max_response_size + 1)
                if len(body) > self._max_response_size:
                    raise ProviderResponseTooLargeError(
                        f"Response {len(body)} bytes exceeds limit {self._max_response_size}"
                    )
                return resp.status, body
        except urllib.error.HTTPError as e:
            if e.code == 301 or e.code == 302 or e.code == 303 or \
               e.code == 307 or e.code == 308:
                raise ProviderHTTPError(e.code, "redirect not allowed")
            try:
                body = e.read(self._max_response_size + 1)
            except Exception:
                body = b""
            raise ProviderHTTPError(e.code, body.decode("utf-8", errors="replace")[:200])
        except urllib.error.URLError as e:
            reason = str(e.reason)
            if "timed out" in reason.lower() or "timeout" in reason.lower():
                raise ProviderTimeoutError(reason) from e
            if isinstance(e.reason, socket.timeout):
                raise ProviderTimeoutError("connection timed out") from e
            raise ProviderTransportError(reason) from e
        except socket.timeout as e:
            raise ProviderTimeoutError("connection timed out") from e
        except socket.gaierror as e:
            raise ProviderTransportError(f"DNS error: {e}") from e
        except (ProviderTimeoutError, ProviderHTTPError, ProviderResponseTooLargeError):
            raise

    def _extract_host(self, url: str) -> str | None:
        from urllib.parse import urlparse
        try:
            parts = urlparse(url)
            return parts.hostname
        except Exception:
            return None

    def _validate_destination(self, hostname: str) -> None:
        if not hostname:
            raise ProviderTransportError("missing hostname")

        hostname_lower = hostname.lower()

        # Development/testing: allow HTTP only for localhost/loopback
        if self._environment in ("testing", "development"):
            if self._allow_http_for_localhost:
                try:
                    ip = ipaddress.ip_address(hostname_lower)
                    if ip.is_loopback:
                        return
                except ValueError:
                    pass
                if hostname_lower in ("localhost", "localhost.localdomain"):
                    return

        # Staging/production: reject private, loopback, link-local, etc.
        try:
            ip = ipaddress.ip_address(hostname_lower)
        except ValueError:
            # hostname - verify via resolver if possible
            return

        if ip.is_loopback:
            raise ProviderTransportError(
                "destination is loopback address"
            )
        if ip.is_private:
            raise ProviderTransportError(
                "destination is private address"
            )
        if ip.is_link_local:
            raise ProviderTransportError(
                "destination is link-local address"
            )
        if ip.is_multicast:
            raise ProviderTransportError(
                "destination is multicast address"
            )
        if ip.is_reserved:
            raise ProviderTransportError(
                "destination is reserved address"
            )
        if ip.is_unspecified:
            raise ProviderTransportError(
                "destination is unspecified address"
            )


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Handler that blocks all HTTP redirects."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

TASK_NAMES = frozenset({"editorial_plan", "edition_draft"})

_CORRELATION_PREFIX = "lt-req-"


def _make_correlation_id(request_id: str) -> str:
    """Derive an opaque correlation ID from the request_id."""
    hasher = hashlib.sha256(request_id.encode("utf-8"))
    return hasher.hexdigest()[:32]


class OpenAICompatibleProvider:
    """Structured-generation provider for OpenAI-compatible chat-completions APIs.

    Parameters
    ----------
    base_url:
        Full chat-completions URL (e.g. ``https://api.openai.com/v1/chat/completions``).
    api_key:
        Bearer-token credential.
    model:
        Model identifier (e.g. ``gpt-4o-mini``).
    timeout_seconds:
        Per-request timeout.
    cost_class:
        Cost class assigned to every result from this provider.
    transport:
        Injectable HTTP transport (defaults to ``UrllibTransport``).
    """

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
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._cost_class = cost_class
        self._environment = environment
        self._transport = transport or UrllibTransport(environment=environment)

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
        start = time.monotonic()

        if task_name not in TASK_NAMES:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=(time.monotonic() - start) * 1000,
                success=False,
                error_category=ProviderErrorCategory.unknown,
                error_message=f"unsupported task: {task_name}",
            )

        try:
            body = self._build_request_body(system_prompt, user_payload)
            status, raw = self._do_request(body)
        except TimeoutError:
            return self._fail_result(start, ProviderErrorCategory.timeout, "provider request timed out")
        except ProviderResponseTooLargeError:
            return self._fail_result(start, ProviderErrorCategory.provider_error, "provider response too large")
        except ProviderHTTPError as e:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=(time.monotonic() - start) * 1000,
                success=False,
                error_category=ProviderErrorCategory.provider_error,
                error_message=f"provider returned http {e.status_code}",
            )
        except ProviderTransportError as e:
            return ProviderResult(
                provider=self._provider_name,
                model=self._model,
                cost_class=self._cost_class,
                latency_ms=(time.monotonic() - start) * 1000,
                success=False,
                error_category=ProviderErrorCategory.provider_error,
                error_message="provider request failed",
            )
        except Exception:
            return self._fail_result(start, ProviderErrorCategory.unknown, "unexpected error")

        latency_ms = (time.monotonic() - start)

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

        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "provider returned malformed JSON")

        usage = parsed.get("usage") or {}
        prompt_tokens = usage.get("prompt_tokens", 0) or 0
        completion_tokens = usage.get("completion_tokens", 0) or 0

        try:
            choices = parsed["choices"]
        except (KeyError, TypeError, ValueError):
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "provider response missing choices")

        if not isinstance(choices, list) or len(choices) == 0:
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "provider returned empty choices")

        message = choices[0].get("message", {})
        content = message.get("content", "")

        if not content or not isinstance(content, str):
            return self._fail_result(start, ProviderErrorCategory.invalid_json, "provider returned empty content")

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
            latency_ms=(time.monotonic() - start) * 1000,
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

    def _do_request(self, body: bytes) -> tuple[int, bytes]:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "X-Request-ID": _make_correlation_id(_make_correlation_id("temp")),  # transient for now
        }
        return self._transport.request(
            self._base_url,
            data=body,
            headers=headers,
            timeout=self._timeout,
        )