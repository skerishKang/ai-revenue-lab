"""One-command B14 Provider/model onboarding: probe the real adapter, then emit one row.

Why this exists
---------------
A B14 OpenAI-compatible Provider no longer has its own Python module. Its
identity, fixed origin, credential slot NAME and any static extra request
headers live in `apps/korean-ai-platform/app/pilot/b14_models.json`, and
`app.pilot.platform` is the single adapter that calls it. Adding a model is a
registry row; adding a Provider is a registry row plus the key on its host.

What this tool does
-------------------
1. Probe through the same adapter Production uses (`app.pilot.platform`):
   completed answer, Korean output, streaming answer, latency per stage, and the
   adapter's error code when a stage fails.
2. If the probe passes, build the exact append-only registry row and print it.
   `--write` applies it through the canonical validated writer.
3. `--offline` performs every stage against a MockTransport: no socket, no key,
   no upstream call. The error-mapping stages (401/429/500) run only offline so
   a live check never spends a request to provoke a failure.

Secret handling: the tool reads the Provider's declared credential binding name
from the process environment and never prints, stores or returns its value. The
offline mode installs a non-credential placeholder in-process only, so the real
Authorization header shape is exercised without touching a real key.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import importlib.util
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = ROOT / "apps" / "korean-ai-platform"
REGISTRY = APP_ROOT / "app" / "pilot" / "b14_models.json"
QUICK_ADD = ROOT / ".github" / "scripts" / "b14_model_quick_add.py"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from app.pilot import platform  # noqa: E402
from app.pilot.errors import PilotError  # noqa: E402
from app.pilot.model_registry_file import (  # noqa: E402
    ModelRegistryError, install_models, read_registry, retired_model_ids,
    validate_registry, write_registry,
)
from app.pilot.platform_secrets import (  # noqa: E402
    CredentialSource, PlatformProviderSpec, get_platform_provider,
    register_platform_provider, unregister_platform_provider,
)

# The adapter resolves the Provider spec from the process registry, which the
# app installs from the same JSON at boot. A standalone CLI must do it too.
install_models()

KOREAN_PROMPT = "한국어로 '통과'라고만 답하세요."
KOREAN_TEXT = re.compile(r"[가-힣]")
OFFLINE_KEY = "offline-probe-not-a-credential"

PROVIDER_KEYS = {
    "base_origin", "allowed_hosts", "credential_source",
    "credential_binding_name", "enabled",
}


class ProbeBlocked(RuntimeError):
    """One bounded failure: stage plus the adapter's own code, never raw body."""

    def __init__(self, stage: str, code: str) -> None:
        super().__init__(code)
        self.stage = stage
        self.code = code


def load_quick_add():
    """Reuse the canonical registration validators instead of a second copy."""
    spec = importlib.util.spec_from_file_location("b14_model_quick_add", QUICK_ADD)
    if spec is None or spec.loader is None:
        raise ProbeBlocked("registry", "quick_add_validator_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _first_text(response: dict[str, Any]) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    return ""


def _error_code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    return type(exc).__name__


def _failure_reason(exc: BaseException) -> str:
    """A bounded, value-free reason: adapter code, validator token, or type."""
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        return code
    reason = getattr(exc, "reason", None)
    if isinstance(reason, str) and reason:
        return reason
    return (str(exc)[:80] if str(exc) else type(exc).__name__)


async def _completed(
    *, model_id: str, upstream: str, provider_name: str, provider_id: str,
    transport: httpx.AsyncBaseTransport | None, max_tokens: int,
) -> tuple[str, int]:
    started = time.monotonic()
    response = await platform.call_platform_chat_completions(
        model_id=model_id,
        upstream_model=upstream,
        provider=provider_name,
        platform_provider_id=provider_id,
        messages=[{"role": "user", "content": KOREAN_PROMPT}],
        max_tokens=max_tokens,
        transport=transport,
    )
    return _first_text(response), int((time.monotonic() - started) * 1000)


async def _stream(
    *, model_id: str, upstream: str, provider_name: str, provider_id: str,
    transport: httpx.AsyncBaseTransport | None, max_tokens: int,
) -> tuple[str, int | None, int, bool]:
    started = time.monotonic()
    first_token: int | None = None
    pieces: list[str] = []
    saw_done = False
    async for event in platform.stream_platform_chat_completions(
        model_id=model_id,
        upstream_model=upstream,
        provider=provider_name,
        platform_provider_id=provider_id,
        messages=[{"role": "user", "content": KOREAN_PROMPT}],
        max_tokens=max_tokens,
        transport=transport,
    ):
        if getattr(event, "delta_content", None):
            if first_token is None:
                first_token = int((time.monotonic() - started) * 1000)
            pieces.append(event.delta_content)
        if getattr(event, "done", False):
            saw_done = True
    return "".join(pieces), first_token, int((time.monotonic() - started) * 1000), saw_done


def _offline_transport(upstream: str, seen: list[dict[str, Any]]) -> httpx.MockTransport:
    """Deterministic upstream: records the request, answers Korean text."""

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({
            "url": str(request.url),
            "headers": {k.lower(): v for k, v in request.headers.items()},
            "body": body,
        })
        if body.get("model") != upstream:
            return httpx.Response(400, json={"error": {"code": "wrong_model"}})
        if body.get("stream") is True:
            frames = [
                {"id": "probe", "model": upstream, "choices": [
                    {"index": 0, "delta": {"content": "통"}, "finish_reason": None}]},
                {"id": "probe", "model": upstream, "choices": [
                    {"index": 0, "delta": {"content": "과"}, "finish_reason": "stop"}]},
            ]
            payload = "".join(
                "data: " + json.dumps(frame) + "\n\n" for frame in frames
            ) + "data: [DONE]\n\n"
            return httpx.Response(
                200, content=payload.encode(),
                headers={"content-type": "text/event-stream"},
            )
        return httpx.Response(200, json={
            "id": "probe",
            "model": upstream,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "통과"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
        })

    return httpx.MockTransport(handler)


async def _offline_error_codes(
    *, model_id: str, upstream: str, provider_name: str, provider_id: str,
) -> dict[str, str]:
    """Prove the adapter's status -> error-code mapping without a real request."""

    codes: dict[str, str] = {}
    for status in (401, 403, 429, 500):

        def handler(_request: httpx.Request, status: int = status) -> httpx.Response:
            return httpx.Response(status, json={"error": {"code": "probe"}})

        try:
            await platform.call_platform_chat_completions(
                model_id=model_id,
                upstream_model=upstream,
                provider=provider_name,
                platform_provider_id=provider_id,
                messages=[{"role": "user", "content": KOREAN_PROMPT}],
                max_tokens=8,
                transport=httpx.MockTransport(handler),
            )
        except PilotError as exc:
            codes[str(status)] = _error_code(exc)
        else:
            codes[str(status)] = "unexpected_success"
    return codes


def _probe_spec(args, registry: dict, headers: list[tuple[str, str]]) -> tuple[PlatformProviderSpec, bool]:
    """The Provider spec to probe, plus whether this process registered it."""
    row = registry["providers"].get(args.provider)
    if row is not None:
        extra = tuple(row.get("extra_headers", {}).items())
        return PlatformProviderSpec(
            provider_id=args.provider,
            credential_source=CredentialSource(row["credential_source"]),
            credential_binding_name=row["credential_binding_name"],
            base_origin=row["base_origin"],
            allowed_hosts=tuple(row["allowed_hosts"]),
            enabled=row["enabled"],
            extra_headers=extra,
        ), False
    binding = "" if args.keyless else args.credential_binding
    spec = PlatformProviderSpec(
        provider_id=args.provider,
        credential_source=(
            CredentialSource.NONE if args.keyless else CredentialSource.PLATFORM_SECRET
        ),
        credential_binding_name=binding,
        base_origin=args.base_url,
        allowed_hosts=tuple(args.allowed_host or _hosts_from(args.base_url)),
        extra_headers=tuple(headers),
    )
    register_platform_provider(spec)
    return spec, True


def _hosts_from(url: str) -> list[str]:
    from urllib.parse import urlsplit

    host = urlsplit(url).hostname
    if not host:
        raise ProbeBlocked("provider", "base_url_host_missing")
    return [host]


def _parse_headers(pairs: list[str] | None) -> list[tuple[str, str]]:
    parsed: list[tuple[str, str]] = []
    for pair in pairs or []:
        name, separator, value = pair.partition(":")
        if not separator or not name.strip():
            raise ProbeBlocked("provider", "extra_header_must_be_name_colon_value")
        parsed.append((name.strip(), value.strip()))
    return parsed


def _new_provider_row(args, headers: list[tuple[str, str]]) -> dict:
    if not args.provider_name:
        raise ProbeBlocked("registry", "provider_name_required_for_new_provider")
    row = {
        "base_origin": args.base_url,
        "allowed_hosts": list(args.allowed_host or _hosts_from(args.base_url)),
        "credential_source": "none" if args.keyless else "platform_secret",
        "credential_binding_name": "" if args.keyless else args.credential_binding,
        "enabled": True,
    }
    if headers:
        row["extra_headers"] = dict(headers)
    return row


def _model_row(args, registry: dict, updated: dict, provider_name: str,
               is_new_provider: bool) -> dict:
    quick = load_quick_add()
    if not is_new_provider:
        return quick.make_candidate(
            registry,
            provider=args.provider,
            upstream=args.upstream,
            name=args.name,
            source=args.source,
            checked_at=args.checked_at,
            capabilities=args.capability or ["chat"],
            context_window=args.context_window,
        )
    from urllib.parse import urlsplit

    url = urlsplit(args.source or "")
    if url.scheme != "https" or not url.netloc or url.username or url.password:
        raise ProbeBlocked("registry", "official_source_must_be_https")
    tags = sorted(set(args.capability or ["chat"]))
    if not tags or "chat" not in tags or not set(tags) <= {"chat", "coding", "image"}:
        raise ProbeBlocked("registry", "unsupported_or_unverified_capability")
    try:
        date.fromisoformat(args.checked_at)
    except (TypeError, ValueError) as exc:
        raise ProbeBlocked("registry", "source_checked_date_invalid") from exc
    return {
        "id": args.model_id,
        "provider_id": args.provider,
        "upstream_model": args.upstream,
        "display_name": args.name,
        "provider_name": provider_name,
        "capabilities": tags,
        "context_window": args.context_window,
        "input_price_usd_per_1m": None,
        "output_price_usd_per_1m": None,
        "source": args.source,
        "source_checked_at": args.checked_at,
        "enabled": True,
    }


def _apply_row(registry: dict, args, headers: list[tuple[str, str]]) -> tuple[dict, dict]:
    quick = load_quick_add()
    is_new_provider = args.provider not in registry["providers"]
    updated = copy.deepcopy(registry)
    if is_new_provider:
        updated["providers"][args.provider] = _new_provider_row(args, headers)
    provider_name = next(
        (m["provider_name"] for m in registry["models"] if m["provider_id"] == args.provider),
        args.provider_name,
    )
    row = _model_row(args, registry, updated, provider_name, is_new_provider)
    updated["models"].append(row)
    if not quick.exact_append_only(registry, updated):
        raise ProbeBlocked("registry", "change_not_safe_append_only")
    validate_registry(updated)
    # The canonical owner gate: every enabled row must be an owner-allowed one.
    quick.check_candidate_json(updated, REGISTRY)
    return row, updated


async def run(args) -> tuple[int, dict]:
    registry = read_registry(REGISTRY)
    if args.model_id.split("/", 1)[0] != args.provider:
        raise ProbeBlocked("input", "model_id_must_start_with_provider_id")
    upstream = args.model_id.split("/", 1)[1]
    if not upstream:
        raise ProbeBlocked("input", "upstream_model_missing")
    args.upstream = upstream
    if args.model_id in retired_model_ids():
        raise ProbeBlocked("input", "model_id_is_retired")
    if args.write and args.probe_only:
        raise ProbeBlocked("input", "write_and_probe_only_are_exclusive")

    headers = _parse_headers(args.extra_header)
    spec, temporary = _probe_spec(args, registry, headers)
    previous = get_platform_provider(args.provider) if not temporary else None
    previous_mode = os.environ.get("B14_PROVIDER_MODE")
    injected_key = False
    previous_key: str | None = None
    if spec.credential_source == CredentialSource.PLATFORM_SECRET and args.offline:
        binding = spec.credential_binding_name
        previous_key = os.environ.get(binding)
        if not previous_key:
            os.environ[binding] = OFFLINE_KEY
            injected_key = True
    os.environ["B14_PROVIDER_MODE"] = "live"
    seen: list[dict[str, Any]] = []
    transport = _offline_transport(upstream, seen) if args.offline else None
    provider_name = next(
        (m["provider_name"] for m in registry["models"] if m["provider_id"] == args.provider),
        args.provider_name or args.provider,
    )
    report: dict[str, Any] = {
        "status": "BLOCKED",
        "mode": "offline" if args.offline else "live",
        "provider": args.provider,
        "model_id": args.model_id,
        "upstream_model": upstream,
        "network": "mock_transport" if args.offline else "https",
        "provider_api_posts": 0,
        "production_mutation": False,
    }

    try:
        answer, completed_ms = await _completed(
            model_id=args.model_id, upstream=upstream, provider_name=provider_name,
            provider_id=args.provider, transport=transport, max_tokens=args.max_tokens,
        )
        report["provider_api_posts"] += 1
        report["checks"] = {
            "response": bool(answer.strip()),
            "korean": bool(KOREAN_TEXT.search(answer)),
        }
        report["sample"] = answer.strip()[:80]
        report["latency_ms"] = {"completed": completed_ms}

        stream_text, first_token, stream_ms, saw_done = await _stream(
            model_id=args.model_id, upstream=upstream, provider_name=provider_name,
            provider_id=args.provider, transport=transport, max_tokens=args.max_tokens,
        )
        report["provider_api_posts"] += 1
        report["checks"]["streaming"] = bool(stream_text.strip())
        report["checks"]["stream_done"] = saw_done
        report["latency_ms"].update(
            {"first_token": first_token, "stream_total": stream_ms}
        )

        if args.offline:
            codes = await _offline_error_codes(
                model_id=args.model_id, upstream=upstream,
                provider_name=provider_name, provider_id=args.provider,
            )
            report["checks"]["error_codes"] = codes
            if len(set(codes.values())) < 3:
                raise ProbeBlocked("error_mapping", "error_codes_not_distinct")
            if any(code.startswith("unexpected") for code in codes.values()):
                raise ProbeBlocked("error_mapping", "error_status_accepted")
            body = seen[0]["body"] if seen else {}
            report["checks"]["model_echo"] = body.get("model") == upstream
            report["request_headers"] = sorted(seen[0]["headers"]) if seen else []
            if seen and "authorization" in seen[0]["headers"] and args.offline:
                report["auth_header_shape"] = seen[0]["headers"]["authorization"].startswith(
                    "Bearer "
                )
        else:
            report["checks"]["error_codes"] = {}

        if not all(
            report["checks"][key] for key in ("response", "korean", "streaming", "stream_done")
        ):
            raise ProbeBlocked("answer", "answer_contract_not_met")

        if not args.probe_only:
            row, updated = _apply_row(registry, args, headers)
            if args.write:
                write_registry(updated, REGISTRY)
                report["production_mutation"] = False
                report["registration"] = {
                    "mode": "JSON_APPENDED", "row": row,
                    "model_count_after": len(updated["models"]),
                    "next": "one PR + B14 CI; deployment is a separate authorized step",
                }
            else:
                report["registration"] = {
                    "mode": "DRY_RUN", "row": row,
                    "model_count_after": len(updated["models"]),
                    "next": "re-run with --write to append the row",
                }

        report["status"] = "PASS"
        return 0, report
    finally:
        if injected_key:
            if previous_key is None:
                os.environ.pop(spec.credential_binding_name, None)
            else:
                os.environ[spec.credential_binding_name] = previous_key
        if previous_mode is None:
            os.environ.pop("B14_PROVIDER_MODE", None)
        else:
            os.environ["B14_PROVIDER_MODE"] = previous_mode
        if temporary:
            unregister_platform_provider(args.provider)
        elif previous is not None and spec != previous:
            register_platform_provider(previous)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = argparse.ArgumentParser(
        description="Probe a B14 OpenAI-compatible provider/model, then emit one registry row"
    )
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model-id", required=True, help="exact public id: <provider>/<upstream>")
    parser.add_argument("--name", default="", help="display name for the registry row")
    parser.add_argument("--source", default="", help="official https model specification")
    parser.add_argument("--checked-at", default=date.today().isoformat())
    parser.add_argument("--capability", action="append", default=None)
    parser.add_argument("--context-window", type=int, default=0)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--offline", action="store_true",
                        help="no socket: MockTransport for every stage")
    parser.add_argument("--probe-only", action="store_true", help="do not build a row")
    parser.add_argument("--write", action="store_true", help="append the row to the registry")
    parser.add_argument("--create-provider", action="store_true",
                        help="also add a new Provider row (one-time credential review)")
    parser.add_argument("--provider-name", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--allowed-host", action="append")
    parser.add_argument("--credential-binding", default="")
    parser.add_argument("--keyless", action="store_true")
    parser.add_argument("--extra-header", action="append", metavar="NAME:VALUE")
    args = parser.parse_args(argv)

    try:
        code, report = asyncio.run(run(args))
    except ProbeBlocked as exc:
        report = {
            "status": "BLOCKED", "stage": exc.stage, "reason": exc.code,
            "provider": args.provider, "model_id": args.model_id,
            "network": "mock_transport" if args.offline else "https",
            "provider_api_posts": 0, "production_mutation": False,
        }
        code = 2
    except (PilotError, ModelRegistryError, OSError, ValueError, KeyError, TypeError) as exc:
        report = {
            "status": "BLOCKED",
            "stage": "adapter",
            "reason": _failure_reason(exc),
            "provider": args.provider, "model_id": args.model_id,
            "network": "mock_transport" if args.offline else "https",
            "provider_api_posts": 0, "production_mutation": False,
        }
        code = 2
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())