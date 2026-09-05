"""Product entry-point wiring for the P01 Engine orchestration port.

This module is the only KAgent authority that turns environment settings into
a live ``P01CoreOrchestrationAdapter``. Missing or partial configuration fails
closed with an explicit ``P01AdapterError``; the ``p01-run`` flow never falls
back to the B14 demo/mock path. No endpoint, caller, or credential value is
hardcoded here: the only constants are the environment variable names and the
internal origin marker owned by the Engine client contract.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

from padiem_ai_engine_client import (
    ENGINE_INTERNAL_ORIGIN,
    EngineTransportResponse,
    PadiemAiEngineClient,
    PadiemAiEngineClientError,
)

from .contracts import ClawRunStatus, ClawTaskIntent, ExecutionMode
from .core import redact_secrets
from .p01_adapter import (
    P01_APP_ID,
    ClawOrchestrationOutcome,
    P01AdapterError,
    P01CoreOrchestrationAdapter,
)
from .p01_orchestration_client import P01EngineOrchestrationClient
from .runs import ClawRun

ENV_ENGINE_BASE_URL = "P01_ENGINE_BASE_URL"
ENV_ENGINE_CALLER_ID = "P01_ENGINE_CALLER_ID"
ENV_ENGINE_CREDENTIAL = "P01_ENGINE_CREDENTIAL"

# The Engine caps one orchestration budget at 60s; the socket timeout adds a
# fixed margin so a stalled connection fails closed instead of hanging the CLI.
TRANSPORT_TIMEOUT_SECONDS = 90.0

# Bounded response read. Matches the ingress worker's own response ceiling so
# the direct engine path never accepts a larger body than the canonical
# server-to-server path.
MAX_ENGINE_RESPONSE_BYTES = 1024 * 1024

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _misconfigured(message: str) -> P01AdapterError:
    return P01AdapterError("p01_engine_misconfigured", message)


def _validated_base_url(value: object, source: str) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    while normalized.endswith("/"):
        normalized = normalized[:-1]
    parsed = urllib.parse.urlsplit(normalized)
    if (
        not normalized
        or parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise _misconfigured(
            f"{source} must be an absolute http(s) URL without credentials, query, or fragment."
        )
    if parsed.scheme == "http" and (parsed.hostname or "").lower() not in _LOOPBACK_HOSTS:
        raise _misconfigured(
            f"{source} may use http:// only for a loopback dev instance "
            "(127.0.0.1, localhost, or ::1); use https:// for any other host."
        )
    return normalized


@dataclass(frozen=True, slots=True)
class P01EngineRuntimeConfig:
    base_url: str
    caller_id: str
    credential: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "base_url", _validated_base_url(self.base_url, ENV_ENGINE_BASE_URL)
        )
        caller = self.caller_id.strip() if isinstance(self.caller_id, str) else ""
        if not caller or len(caller) > 64 or any(char.isspace() for char in caller):
            raise _misconfigured(
                f"{ENV_ENGINE_CALLER_ID} must be a short identifier without spaces."
            )
        object.__setattr__(self, "caller_id", caller)
        credential = self.credential if isinstance(self.credential, str) else ""
        byte_length = len(credential.encode("utf-8"))
        if not 32 <= byte_length <= 512:
            raise _misconfigured(
                f"{ENV_ENGINE_CREDENTIAL} must contain 32 to 512 bytes."
            )


class UrllibEngineTransport:
    """Stdlib-only Engine transport mapped onto the configured base URL."""

    def __init__(self, base_url: str, *, timeout_seconds: float = TRANSPORT_TIMEOUT_SECONDS) -> None:
        self._base_url = _validated_base_url(base_url, ENV_ENGINE_BASE_URL)
        self._timeout = float(timeout_seconds)

    def map_url(self, url: str) -> str:
        parsed = urllib.parse.urlsplit(url)
        if f"{parsed.scheme}://{parsed.netloc}" != ENGINE_INTERNAL_ORIGIN:
            raise P01AdapterError(
                "p01_engine_url_invalid",
                "Engine request URL is outside the internal origin.",
            )
        suffix = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        return f"{self._base_url}{suffix}"

    async def request(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes | None,
    ) -> EngineTransportResponse:
        return await asyncio.to_thread(
            self._request_sync, method, self.map_url(url), dict(headers), body
        )

    def _request_sync(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None
    ) -> EngineTransportResponse:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return self._bounded_response(
                    int(response.status),
                    response.read(MAX_ENGINE_RESPONSE_BYTES + 1),
                    dict(response.headers),
                )
        except urllib.error.HTTPError as exc:
            return self._bounded_response(
                int(exc.code),
                exc.read(MAX_ENGINE_RESPONSE_BYTES + 1),
                dict(exc.headers or {}),
            )
        except (urllib.error.URLError, TimeoutError, OSError):
            raise P01AdapterError(
                "p01_engine_unreachable",
                "P01 Engine endpoint could not be reached.",
            ) from None

    @staticmethod
    def _bounded_response(
        status: int, body: bytes, headers: dict[str, str]
    ) -> EngineTransportResponse:
        if len(body) > MAX_ENGINE_RESPONSE_BYTES:
            raise P01AdapterError(
                "p01_engine_response_too_large",
                "P01 Engine response exceeds the bounded read size.",
            )
        return EngineTransportResponse(status=status, body=body, headers=headers)


def p01_config_from_environment(
    environ: Mapping[str, str] | None = None,
) -> P01EngineRuntimeConfig:
    env = os.environ if environ is None else environ
    values = {
        name: (env.get(name) or "").strip()
        for name in (ENV_ENGINE_BASE_URL, ENV_ENGINE_CALLER_ID, ENV_ENGINE_CREDENTIAL)
    }
    if not any(values.values()):
        raise P01AdapterError(
            "p01_engine_not_configured",
            "P01 Engine client is not configured; set "
            + ", ".join(
                (ENV_ENGINE_BASE_URL, ENV_ENGINE_CALLER_ID, ENV_ENGINE_CREDENTIAL)
            )
            + ". The p01-run flow never falls back to the demo path.",
        )
    missing = sorted(name for name, value in values.items() if not value)
    if missing:
        raise _misconfigured(
            "Missing P01 Engine settings: " + ", ".join(missing) + "."
        )
    return P01EngineRuntimeConfig(
        base_url=values[ENV_ENGINE_BASE_URL],
        caller_id=values[ENV_ENGINE_CALLER_ID],
        credential=values[ENV_ENGINE_CREDENTIAL],
    )


def build_p01_orchestration_adapter(
    config: P01EngineRuntimeConfig,
    *,
    transport: object | None = None,
) -> P01CoreOrchestrationAdapter:
    engine_transport = (
        transport if transport is not None else UrllibEngineTransport(config.base_url)
    )
    try:
        client = PadiemAiEngineClient(
            transport=engine_transport,  # type: ignore[arg-type]
            app_id=P01_APP_ID,
            caller_id=config.caller_id,
            credential=config.credential,
        )
    except PadiemAiEngineClientError:
        raise _misconfigured(
            "P01 Engine client configuration was rejected by the Engine client contract."
        ) from None
    return P01CoreOrchestrationAdapter(P01EngineOrchestrationClient(client))


def p01_adapter_from_environment(
    environ: Mapping[str, str] | None = None,
    *,
    transport: object | None = None,
) -> P01CoreOrchestrationAdapter:
    return build_p01_orchestration_adapter(
        p01_config_from_environment(environ), transport=transport
    )


def create_claw_run(
    repository_ref: str, task: str, *, run_id: str | None = None
) -> ClawRun:
    provided = run_id.strip() if isinstance(run_id, str) else ""
    if provided and not provided.startswith("run_"):
        raise P01AdapterError(
            "p01_run_id_invalid", "Explicit run ids must start with 'run_'."
        )
    generated = provided or f"run_{uuid.uuid4().hex[:24]}"
    suffix = generated[4:] if generated.startswith("run_") else generated
    intent = ClawTaskIntent(
        task_id=f"task_{suffix}",
        task=task,
        repository_ref=repository_ref,
        execution_mode=ExecutionMode.LOCAL,
        source_surface="cli",
    )
    return ClawRun.create(generated, intent)


async def execute_p01_claw_task(
    repository_ref: str,
    task: str,
    adapter: P01CoreOrchestrationAdapter,
    *,
    run_id: str | None = None,
) -> ClawOrchestrationOutcome:
    run = create_claw_run(repository_ref, task, run_id=run_id)
    return await adapter.execute(run)


def run_p01_task(
    repository: Path,
    task: str,
    *,
    adapter: P01CoreOrchestrationAdapter | None = None,
    environ: Mapping[str, str] | None = None,
    run_id: str | None = None,
) -> int:
    try:
        active = (
            adapter if adapter is not None else p01_adapter_from_environment(environ)
        )
        outcome = asyncio.run(
            execute_p01_claw_task(str(repository), task, active, run_id=run_id)
        )
    except P01AdapterError as exc:
        print(
            f"KAGENT_P01: {exc.code} · {redact_secrets(exc.safe_message)}",
            file=sys.stderr,
        )
        return 2
    print("[P01 ORCHESTRATION]")
    print(
        f"run={outcome.projection.run_id} status={outcome.projection.status.value} "
        f"p01_run={outcome.p01_run_id} events={outcome.p01_event_count}"
    )
    if outcome.answer is not None:
        print(f"answer: {redact_secrets(outcome.answer)[:4000]}")
    print("git=off · demo_fallback=never")
    return 0 if outcome.projection.status is ClawRunStatus.COMPLETED else 1
