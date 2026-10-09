#!/usr/bin/env python3
"""Provider-neutral PAGE-FETCH benchmark runner for Issue #3385.

Companion to `scripts/experiments/benchmark_padiem_search_providers.py`, which is
search-only. This harness covers the Fetch leg only, so the TinyFish shadow
bake-off can be evaluated on both Search and Fetch instead of Search alone.

This is experiment tooling, not a Production provider runtime. It makes at most
one network request per selected corpus URL, never retries, never logs
credentials, and refuses to write live provider results inside the repository.

Three execution modes:

* default            -> ``DRY_RUN_NETWORK_DENIED`` (no network, no fixture)
* ``--fixture FILE`` -> ``OFFLINE_REPLAY`` (no network; synthetic responses replayed
                        from a JSONL fixture, used for offline measurement)
* ``--allow-network`` -> live provider POST (requires an explicit credential env var)

``--fixture`` is network-denied by construction, not by convention: the selected
URL set must be fully covered by the fixture file *before* iteration starts, and
``run_case(offline=True)`` cannot reach the live transport even when a valid
provider credential is present in the process environment. A missing id exits
non-zero with ``MISSING_FIXTURE``; an unreadable, malformed, or duplicate-id
fixture exits with ``INVALID_FIXTURE``. Neither path writes a success record.

Fetch-capable providers are TinyFish and Firecrawl. Daum is inventoried but has no
page-fetch endpoint in Core (``DaumWebProvider.fetch`` raises ``web_fetch_unavailable``),
so it is reported as fetch-unsupported rather than silently dropped.

TinyFish Fetch wire contract (published docs, retrieved 2026-10-10): ``POST
https://api.fetch.tinyfish.ai`` with an ``X-API-Key`` header and a JSON body
``{"urls": [ ... ]}`` (max 10 public http/https URLs), returning
``{"results": [{"url", "final_url", "title", "description", "language", "format",
"text"}], "errors": []}``. This runner implements that documented contract so the
Fetch leg can be measured independently; the Core ``TinyFishWebProvider.fetch``
is aligned to the same contract by the stacked #3957 change.
"""

from __future__ import annotations

import argparse
import base64
from dataclasses import asdict, dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

MAX_RESPONSE_BYTES = 1_048_576
MAX_TEXT_CHARS = 2_000
DEFAULT_TIMEOUT_SECONDS = 20.0
BENCHMARK_VERSION = "padiem-fetch-provider-benchmark-v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = REPO_ROOT / "docs/experiments/PADIEM_FETCH_PROVIDER_BENCHMARK_URLS_v1.tsv"

# Same precedence as the product path (`padiem_ai_core.web_runtime`).
TINYFISH_CONTENT_KEYS = ("text", "markdown", "content", "snippet", "description")
# The published Fetch API envelope is `{"results": [ {...} ], "errors": []}`; the
# `data`/`result` dict envelopes are accepted only as a defensive fallback.
TINYFISH_RESULT_LIST_KEYS = ("results",)
TINYFISH_ENVELOPE_KEYS = ("data", "result")
TINYFISH_URL_KEYS = ("final_url", "url", "source_url")
FIRECRAWL_CONTENT_KEYS = ("markdown", "text")

Transport = Callable[[str, str, dict[str, str], "bytes | None", float], "tuple[int, bytes, dict[str, str]]"]


@dataclass(frozen=True)
class FetchCase:
    id: str
    language: str
    category: str
    url: str
    expectation: str


@dataclass(frozen=True)
class FetchProviderSpec:
    provider: str
    endpoint: str
    credential_env: str
    fetch_supported: bool
    distribution_gate: str
    production_gate: str
    notes: str


@dataclass(frozen=True)
class NormalizedFetch:
    title: str
    url: str
    content: str


class FetchBenchmarkError(RuntimeError):
    code = "FETCH_BENCHMARK_ERROR"


class MissingCredential(FetchBenchmarkError):
    code = "MISSING_CREDENTIAL"


class FetchUnsupported(FetchBenchmarkError):
    code = "FETCH_UNSUPPORTED"


class MissingFixture(FetchBenchmarkError):
    """Offline replay was requested but a selected URL has no fixture entry."""

    code = "MISSING_FIXTURE"


class InvalidFixture(FetchBenchmarkError):
    """The fixture file is unreadable, malformed, or carries duplicate ids."""

    code = "INVALID_FIXTURE"


class ResponseTooLarge(FetchBenchmarkError):
    code = "RESPONSE_TOO_LARGE"


class MalformedResponse(FetchBenchmarkError):
    code = "MALFORMED_RESPONSE"


class TransportError(FetchBenchmarkError):
    code = "TRANSPORT_ERROR"


class BenchmarkHttpError(FetchBenchmarkError):
    def __init__(self, status: int):
        super().__init__(f"provider returned HTTP {status}")
        self.status = status
        # 402 = the provider's free allowance is exhausted (TinyFish documents
        # HTTP 402 / `INSUFFICIENT_CREDITS`). It must abort the run like 429 so a
        # live benchmark can never silently spend past the free quota.
        if status == 402:
            self.code = "HTTP_402"
        elif status == 429:
            self.code = "HTTP_429"
        elif 400 <= status < 500:
            self.code = "HTTP_4XX"
        elif status >= 500:
            self.code = "HTTP_5XX"
        else:
            self.code = "HTTP_ERROR"


PROVIDERS: dict[str, FetchProviderSpec] = {
    "tinyfish": FetchProviderSpec(
        "tinyfish",
        "https://api.fetch.tinyfish.ai",
        "TINYFISH_API_KEY",
        True,
        "internal_results_only",
        "standard_terms_internal_business_use_and_training; public_customer_app_not_eligible_without_separate_agreement",
        "POST one public URL as {\"urls\": [...]}; reads results[].text/final_url/title.",
    ),
    "firecrawl": FetchProviderSpec(
        "firecrawl",
        "https://api.firecrawl.dev/v2/scrape",
        "FIRECRAWL_API_KEY",
        True,
        "internal_results_only",
        "existing_core_provider; default_search_not_preferred_by_owner",
        "POST one normalized public URL with formats=[markdown]; content via data.markdown.",
    ),
    "daum": FetchProviderSpec(
        "daum",
        "",
        "DAUM_REST_API_KEY",
        False,
        "internal_results_only",
        "hold_for_kakao_llm_grounding_terms_issue_1324",
        "Kakao Daum search API has no page-fetch endpoint; Core DaumWebProvider.fetch raises web_fetch_unavailable.",
    ),
}


def _clean_text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str):
        return ""
    value = re.sub(r"<[^>]*>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= limit else value[:limit].rstrip() + "…"


def _safe_url(value: Any) -> str:
    """Public-URL guard, identical in intent to the search benchmark runner."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if len(value) > 2048:
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username is not None or parsed.password is not None:
        return ""
    host = parsed.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan", ".home")):
        return ""
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if re.fullmatch(r"[0-9.]+", host):
            return ""
    else:
        candidate = getattr(address, "ipv4_mapped", None) or address
        if not candidate.is_global:
            return ""
    return value


def load_corpus(path: Path = DEFAULT_CORPUS) -> list[FetchCase]:
    import csv

    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    required = {"id", "language", "category", "url", "expectation"}
    if not rows or set(rows[0]) != required:
        raise ValueError("fetch corpus TSV schema mismatch")
    cases = [
        FetchCase(
            id=row["id"].strip(),
            language=row["language"].strip(),
            category=row["category"].strip(),
            url=row["url"].strip(),
            expectation=row["expectation"].strip(),
        )
        for row in rows
    ]
    if len({case.id for case in cases}) != len(cases):
        raise ValueError("fetch corpus ids must be unique")
    if any(not case.url for case in cases):
        raise ValueError("fetch corpus url must not be empty")
    if any(not _safe_url(case.url) for case in cases):
        raise ValueError("fetch corpus contains a non-public or unsafe url")
    if any(case.language not in {"ko", "en"} for case in cases):
        raise ValueError("fetch corpus language must be ko or en")
    return cases


def provider_public_metadata(spec: FetchProviderSpec) -> dict[str, Any]:
    return {
        "provider": spec.provider,
        "endpoint": spec.endpoint,
        "credential_env": spec.credential_env,
        "credential_configured": bool(os.environ.get(spec.credential_env)),
        "fetch_supported": spec.fetch_supported,
        "distribution_gate": spec.distribution_gate,
        "production_gate": spec.production_gate,
        "notes": spec.notes,
    }


def _request_for(spec: FetchProviderSpec, case: FetchCase, credential: str) -> tuple[str, str, dict[str, str], bytes | None]:
    if not spec.fetch_supported:
        raise FetchUnsupported(f"{spec.provider} has no page-fetch endpoint")
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if spec.provider == "tinyfish":
        headers["X-API-Key"] = credential
        # Published Fetch API request field is `urls` (array, max 10 URLs). Core
        # `TinyFishWebProvider.fetch` sends the same shape after the stacked
        # #3957 alignment; see the runner docstring.
        payload = {"urls": [case.url]}
    elif spec.provider == "firecrawl":
        headers["Authorization"] = f"Bearer {credential}"
        payload = {"url": case.url, "formats": ["markdown"], "onlyMainContent": True}
    else:
        raise FetchUnsupported(f"{spec.provider} has no page-fetch endpoint")
    return "POST", spec.endpoint, headers, json.dumps(payload, ensure_ascii=False).encode("utf-8")


def _decode_json(raw: bytes) -> tuple[dict[str, Any], str, bool]:
    """Decode a provider JSON body, reporting the codec actually used."""
    for encoding in ("utf-8", "utf-16", "cp949", "latin-1"):
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            raise MalformedResponse("provider response must be a JSON object")
        return data, encoding, True
    raise MalformedResponse("provider returned malformed JSON")


def _normalize_fetch(provider: str, data: dict[str, Any]) -> NormalizedFetch:
    if provider == "tinyfish":
        payload: Any = data
        for list_key in TINYFISH_RESULT_LIST_KEYS:
            candidate = payload.get(list_key)
            if isinstance(candidate, list) and candidate and isinstance(candidate[0], dict):
                payload = candidate[0]
                break
        else:
            for envelope in TINYFISH_ENVELOPE_KEYS:
                candidate = payload.get(envelope)
                if isinstance(candidate, dict):
                    payload = candidate
                    break
        if not isinstance(payload, dict) or not any(
            key in payload for key in TINYFISH_CONTENT_KEYS
        ):
            raise MalformedResponse("web page result shape is invalid")
        content = next(
            (payload.get(key) for key in TINYFISH_CONTENT_KEYS if isinstance(payload.get(key), str)),
            "",
        )
        returned_url = next(
            (payload.get(key) for key in TINYFISH_URL_KEYS if isinstance(payload.get(key), str)),
            "",
        )
        title = payload.get("title")
    elif provider == "firecrawl":
        payload = data.get("data")
        if not isinstance(payload, dict):
            raise MalformedResponse("web page result shape is invalid")
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        content = next(
            (payload.get(key) for key in FIRECRAWL_CONTENT_KEYS if isinstance(payload.get(key), str)),
            "",
        ) or (metadata.get("description") if isinstance(metadata.get("description"), str) else "")
        returned_url = metadata.get("sourceURL") or metadata.get("url") or ""
        title = metadata.get("title")
    else:
        raise FetchUnsupported(f"{provider} has no page-fetch endpoint")

    safe_returned = _safe_url(returned_url) or ""
    return NormalizedFetch(
        title=_clean_text(title, 300),
        url=safe_returned,
        content=_clean_text(content),
    )


def _perform_request(
    method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
) -> tuple[int, bytes, dict[str, str]]:
    request = Request(url=url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 200))
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            response_headers = {k.lower(): v for k, v in response.headers.items()}
    except HTTPError as exc:
        raise BenchmarkHttpError(exc.code) from exc
    except (URLError, socket.timeout, TimeoutError) as exc:
        if isinstance(getattr(exc, "reason", None), socket.timeout) or isinstance(
            exc, (socket.timeout, TimeoutError)
        ):
            error = TransportError("provider request timed out")
            error.code = "TIMEOUT"
            raise error from exc
        raise TransportError("provider transport failed") from exc
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ResponseTooLarge("provider response exceeded safe benchmark limit")
    if status < 200 or status >= 300:
        raise BenchmarkHttpError(status)
    return status, raw, response_headers


def _record(
    spec: FetchProviderSpec,
    case: FetchCase,
    *,
    http_status: int | None,
    latency_ms: float | None,
    response_bytes: int,
    content_type: str,
    payload_encoding: str | None,
    decode_ok: bool,
    normalized: NormalizedFetch | None,
    error: str | None,
) -> dict[str, Any]:
    content = normalized.content if normalized else ""
    return {
        "benchmark_version": BENCHMARK_VERSION,
        "provider": spec.provider,
        "url_id": case.id,
        "language": case.language,
        "category": case.category,
        "expectation": case.expectation,
        "url": case.url,
        "http_status": http_status,
        "latency_ms": latency_ms,
        "response_bytes": response_bytes,
        "content_type": content_type,
        "payload_encoding": payload_encoding,
        "decode_ok": decode_ok,
        "content_chars": len(content),
        "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()[:16] if content else "",
        "final_url": normalized.url if normalized else "",
        "title": normalized.title if normalized else "",
        "error": error,
        "distribution_gate": spec.distribution_gate,
    }


def run_case(
    spec: FetchProviderSpec,
    case: FetchCase,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    transport: Transport | None = None,
    fixture: dict[str, Any] | None = None,
    offline: bool = False,
) -> dict[str, Any]:
    """Fetch one URL and return a normalized, secret-free measurement record.

    ``fixture`` replays a synthetic response (offline, no network). Otherwise a
    real credential is required and ``transport`` performs the network call.

    ``offline=True`` is a hard invariant: the live transport is unreachable and a
    missing fixture raises ``MissingFixture`` instead of falling back to the
    network. A fixture passed without ``offline`` still replays offline.
    """
    if not spec.fetch_supported:
        return _record(
            spec, case, http_status=None, latency_ms=None, response_bytes=0,
            content_type="", payload_encoding=None, decode_ok=False,
            normalized=None, error=FetchUnsupported.code,
        )

    if offline or fixture is not None:
        # Offline replay: the network is never reachable from this branch, even
        # when a valid provider credential is present in the process environment.
        if fixture is None:
            raise MissingFixture(f"no offline fixture for url id {case.id}")
        status = int(fixture.get("status", 200))
        raw = base64.b64decode(fixture.get("body_b64", "")) if fixture.get("body_b64") else (
            fixture.get("body", "").encode("utf-8")
        )
        response_headers = {k.lower(): v for k, v in (fixture.get("headers") or {}).items()}
        latency_ms: float | None = None
    else:
        credential = os.environ.get(spec.credential_env, "").strip()
        if not credential:
            raise MissingCredential(f"{spec.credential_env} is not configured")
        method, url, headers, body = _request_for(spec, case, credential)
        status, raw, response_headers = (transport or _perform_request)(method, url, headers, body, timeout)
        latency_ms = None

    if len(raw) > MAX_RESPONSE_BYTES:
        raise ResponseTooLarge("provider response exceeded safe benchmark limit")
    if status < 200 or status >= 300:
        raise BenchmarkHttpError(status)

    data, encoding, decode_ok = _decode_json(raw)
    normalized = _normalize_fetch(spec.provider, data)
    return _record(
        spec, case, http_status=status, latency_ms=latency_ms, response_bytes=len(raw),
        content_type=response_headers.get("content-type", ""), payload_encoding=encoding,
        decode_ok=decode_ok, normalized=normalized, error=None,
    )


def _error_record(spec: FetchProviderSpec, case: FetchCase, exc: FetchBenchmarkError) -> dict[str, Any]:
    return _record(
        spec, case, http_status=getattr(exc, "status", None), latency_ms=None, response_bytes=0,
        content_type="", payload_encoding=None, decode_ok=False, normalized=None, error=exc.code,
    )


def select_cases(
    cases: Iterable[FetchCase],
    url_ids: set[str] | None,
    categories: set[str] | None,
    max_urls: int | None,
) -> list[FetchCase]:
    selected = [
        case
        for case in cases
        if (not url_ids or case.id in url_ids) and (not categories or case.category in categories)
    ]
    if url_ids:
        missing = sorted(url_ids - {case.id for case in selected})
        if missing:
            raise ValueError(f"unknown url ids: {', '.join(missing)}")
    if max_urls is not None:
        if max_urls < 1:
            raise ValueError("--max-urls must be >= 1")
        selected = selected[:max_urls]
    return selected


def load_fixtures(path: Path) -> dict[str, dict[str, Any]]:
    """Load an offline fixture file, rejecting malformed and duplicate rows.

    Raises ``ValueError`` for a row that is not a JSON object, that has no
    non-empty string ``url_id``, that repeats an ``url_id``, or that carries a
    non-integer ``status`` / non-string body. Whitespace-only lines are ignored.
    Raises ``OSError`` when the file itself cannot be read.
    """
    fixtures: dict[str, dict[str, Any]] = {}
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"fixture line {lineno} is not valid JSON") from exc
        if not isinstance(entry, dict):
            raise ValueError(f"fixture line {lineno} must be a JSON object")
        url_id = entry.get("url_id")
        if not isinstance(url_id, str) or not url_id.strip():
            raise ValueError(f"fixture line {lineno} must carry a non-empty string url_id")
        url_id = url_id.strip()
        if url_id in fixtures:
            raise ValueError(f"duplicate fixture url_id: {url_id}")
        if "status" in entry and (isinstance(entry["status"], bool) or not isinstance(entry["status"], int)):
            raise ValueError(f"fixture {url_id} status must be an integer")
        for key in ("body_b64", "body"):
            if key in entry and not isinstance(entry[key], str):
                raise ValueError(f"fixture {url_id} {key} must be a string")
        if "headers" in entry and not isinstance(entry["headers"], dict):
            raise ValueError(f"fixture {url_id} headers must be an object")
        fixtures[url_id] = entry
    return fixtures


def _output_handle(output: str | None):
    if not output:
        return sys.stdout, False
    destination = Path(output).expanduser().resolve()
    try:
        destination.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise ValueError("live benchmark output must stay outside the repository")
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination.open("a", encoding="utf-8"), True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=sorted(PROVIDERS))
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--url-id", action="append", default=[])
    parser.add_argument("--category", action="append", default=[])
    parser.add_argument("--max-urls", type=int)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--output", help="JSONL destination outside the repository")
    parser.add_argument("--allow-network", action="store_true", help="required for live provider requests")
    parser.add_argument("--fixture", type=Path, help="offline JSONL replay of synthetic responses (no network)")
    parser.add_argument("--list-providers", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list_providers:
        for name in sorted(PROVIDERS):
            print(json.dumps(provider_public_metadata(PROVIDERS[name]), ensure_ascii=False, sort_keys=True))
        return 0
    if not args.provider:
        raise SystemExit("--provider is required unless --list-providers is used")
    if args.allow_network and args.fixture:
        raise SystemExit("--allow-network and --fixture are mutually exclusive")

    cases = select_cases(load_corpus(args.corpus), set(args.url_id), set(args.category), args.max_urls)
    spec = PROVIDERS[args.provider]

    fixtures: dict[str, dict[str, Any]] = {}
    if args.fixture:
        try:
            fixtures = load_fixtures(args.fixture)
        except (OSError, ValueError) as exc:
            print(
                json.dumps(
                    {
                        "mode": "OFFLINE_REPLAY",
                        "provider": spec.provider,
                        "error": InvalidFixture.code,
                        "detail": str(exc)[:200],
                        "request_count": 0,
                        "retries": 0,
                        "production_mutation": 0,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 2
        # Coverage is validated BEFORE any iteration, so an incomplete fixture
        # can never fall through to the live transport for a missing id.
        missing = [case.id for case in cases if case.id not in fixtures]
        if missing:
            print(
                json.dumps(
                    {
                        "mode": "OFFLINE_REPLAY",
                        "provider": spec.provider,
                        "error": MissingFixture.code,
                        "missing_url_ids": missing,
                        "request_count": 0,
                        "retries": 0,
                        "production_mutation": 0,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 2

    if not args.allow_network and not args.fixture:
        print(
            json.dumps(
                {
                    "mode": "DRY_RUN_NETWORK_DENIED",
                    "provider": spec.provider,
                    "fetch_supported": spec.fetch_supported,
                    "credential_env": spec.credential_env,
                    "credential_configured": bool(os.environ.get(spec.credential_env)),
                    "selected_urls": [case.id for case in cases],
                    "request_count": len(cases),
                    "retries": 0,
                    "production_mutation": 0,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    offline = bool(args.fixture)
    mode = "OFFLINE_REPLAY" if offline else "LIVE"
    handle, should_close = _output_handle(args.output)
    try:
        for case in cases:
            try:
                record = run_case(
                    spec, case, timeout=args.timeout,
                    fixture=fixtures.get(case.id), offline=offline,
                )
            except FetchBenchmarkError as exc:
                record = _error_record(spec, case, exc)
                record["mode"] = mode
                print(json.dumps(record, ensure_ascii=False, sort_keys=True), file=handle, flush=True)
                if exc.code in {"MISSING_CREDENTIAL", "MISSING_FIXTURE", "HTTP_402", "HTTP_429"}:
                    return 2
                continue
            record["mode"] = mode
            print(json.dumps(record, ensure_ascii=False, sort_keys=True), file=handle, flush=True)
    finally:
        if should_close:
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
