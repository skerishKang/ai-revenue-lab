#!/usr/bin/env python3
"""Non-mutating deployed streaming-chain parity audit for Padiem Chat.

Browser assets and the B14 POST-only streaming surface are checked with GET.
The B62 stream route is framework-aware: a single empty/malformed POST must
fail closed as ``422 invalid_request`` before quota, history, B14 or provider
execution. No valid chat request is sent by this audit.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = "b62-deployed-parity/1.2"
MAX_PUBLIC_BODY_BYTES = 2_097_152
B62_STREAM_PATH = "/api/chat/stream"
B14_AUTO_STREAM_PATH = "/api/pilot/v1/chat/completions/auto-stream-preview"
ASSETS = (
    ("APP_JS", "/app.js", Path("apps/padiem-chat/static/app.js")),
    ("SEARCH_SOURCES_JS", "/search-sources.js", Path("apps/padiem-chat/static/search-sources.js")),
    ("RICH_RESPONSE_JS", "/rich-response.js", Path("apps/padiem-chat/static/rich-response.js")),
)


class AuditError(RuntimeError):
    """Raised when the parity audit itself cannot be trusted."""


@dataclass(frozen=True, slots=True)
class HTTPResult:
    status: int
    headers: dict[str, str]
    body: bytes


@dataclass(frozen=True, slots=True)
class ParityResult:
    asset_parity: dict[str, bool]
    stream_route_present: bool
    stream_get_status: int
    stream_probe_status: int
    stream_probe_error_code: str | None
    b14_auto_stream_route_present: bool
    b14_auto_stream_get_status: int

    @property
    def b62_ready(self) -> bool:
        return all(self.asset_parity.values()) and self.stream_route_present

    @property
    def ready(self) -> bool:
        return self.b62_ready and self.b14_auto_stream_route_present


def normalized_base_url(value: str, env_name: str = "B62_BASE_URL") -> str:
    raw = str(value or "").strip().rstrip("/")
    parsed = urlparse(raw)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        raise AuditError(f"{env_name} must be a bare https origin")
    if not parsed.hostname.endswith(".workers.dev"):
        raise AuditError(f"{env_name} must target a deployment-owned workers.dev origin")
    return raw


def _read_bounded(response: Any) -> bytes:
    body = response.read(MAX_PUBLIC_BODY_BYTES + 1)
    if len(body) > MAX_PUBLIC_BODY_BYTES:
        raise AuditError("public parity response exceeded the bounded body limit")
    return body


def _http_result_from_error(exc: HTTPError) -> HTTPResult:
    try:
        body = exc.read(MAX_PUBLIC_BODY_BYTES + 1)
    finally:
        exc.close()
    if len(body) > MAX_PUBLIC_BODY_BYTES:
        raise AuditError("public parity error response exceeded the bounded body limit")
    return HTTPResult(
        int(exc.code),
        {str(k).lower(): str(v) for k, v in exc.headers.items()},
        body,
    )


def fetch_get(
    url: str,
    *,
    opener: Callable[..., Any] = urlopen,
) -> HTTPResult:
    request = Request(
        url,
        headers={"Accept": "*/*", "User-Agent": USER_AGENT},
        method="GET",
    )
    try:
        with opener(request, timeout=20) as response:
            return HTTPResult(
                int(response.status),
                {str(k).lower(): str(v) for k, v in response.headers.items()},
                _read_bounded(response),
            )
    except HTTPError as exc:
        return _http_result_from_error(exc)
    except URLError as exc:
        raise AuditError("network error while reading a public streaming surface") from exc
    except AuditError:
        raise
    except Exception as exc:
        raise AuditError("unexpected error while reading a public streaming surface") from exc


def fetch_invalid_post(
    url: str,
    *,
    opener: Callable[..., Any] = urlopen,
) -> HTTPResult:
    request = Request(
        url,
        data=b"",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with opener(request, timeout=20) as response:
            return HTTPResult(
                int(response.status),
                {str(k).lower(): str(v) for k, v in response.headers.items()},
                _read_bounded(response),
            )
    except HTTPError as exc:
        return _http_result_from_error(exc)
    except URLError as exc:
        raise AuditError("network error while probing the public B62 stream route") from exc
    except AuditError:
        raise
    except Exception as exc:
        raise AuditError("unexpected error while probing the public B62 stream route") from exc


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def asset_matches(
    *,
    base_url: str,
    public_path: str,
    local_path: Path,
    fetcher: Callable[[str], HTTPResult] = fetch_get,
) -> bool:
    result = fetcher(base_url + public_path)
    if result.status == 404:
        return False
    if result.status != 200:
        raise AuditError(f"unexpected HTTP {result.status} while reading public browser asset")
    try:
        local = local_path.read_bytes()
    except OSError as exc:
        raise AuditError("local browser asset is unavailable for parity comparison") from exc
    return _sha256(result.body) == _sha256(local)


def _post_only_get_probe(
    *,
    base_url: str,
    path: str,
    label: str,
    fetcher: Callable[[str], HTTPResult] = fetch_get,
) -> tuple[bool, int]:
    result = fetcher(base_url + path)
    if result.status == 405:
        allow = result.headers.get("allow", "")
        if allow and "POST" not in {item.strip().upper() for item in allow.split(",")}:
            raise AuditError(f"{label} returned 405 without POST in Allow header")
        return True, result.status
    if result.status == 404:
        return False, result.status
    raise AuditError(f"unexpected HTTP {result.status} while probing {label}")


def _error_code(body: bytes) -> str | None:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError("B62 invalid-POST probe did not return JSON") from exc
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    return code if isinstance(code, str) else None


def stream_route_probe(
    *,
    base_url: str,
    poster: Callable[[str], HTTPResult] = fetch_invalid_post,
) -> tuple[bool, int, str | None]:
    """Prove B62 route existence without authorizing quota or provider execution."""

    result = poster(base_url + B62_STREAM_PATH)
    code = _error_code(result.body) if result.status == 422 else None
    if result.status == 422 and code == "invalid_request":
        return True, result.status, code
    if result.status == 404:
        return False, result.status, code
    if result.status == 422:
        raise AuditError(
            "B62 invalid-POST probe returned 422 without the expected invalid_request signature"
        )
    raise AuditError(f"unexpected HTTP {result.status} while probing public B62 stream route")


def b14_auto_stream_route_probe(
    *,
    base_url: str,
    fetcher: Callable[[str], HTTPResult] = fetch_get,
) -> tuple[bool, int]:
    return _post_only_get_probe(
        base_url=base_url,
        path=B14_AUTO_STREAM_PATH,
        label="public B14 auto-stream route",
        fetcher=fetcher,
    )


def audit(
    *,
    base_url: str,
    b14_base_url: str,
    repo_root: Path,
    fetcher: Callable[[str], HTTPResult] = fetch_get,
    poster: Callable[[str], HTTPResult] = fetch_invalid_post,
) -> ParityResult:
    origin = normalized_base_url(base_url, "B62_BASE_URL")
    b14_origin = normalized_base_url(b14_base_url, "B14_BASE_URL")
    parity: dict[str, bool] = {}
    for name, public_path, relative_path in ASSETS:
        parity[name] = asset_matches(
            base_url=origin,
            public_path=public_path,
            local_path=repo_root / relative_path,
            fetcher=fetcher,
        )

    # Keep the historic GET observation for diagnostics. With the terminal StaticFiles
    # mount, a deployed POST-only B62 route can legitimately return GET=404.
    stream_get = fetcher(origin + B62_STREAM_PATH)
    if stream_get.status not in (404, 405):
        raise AuditError(
            f"unexpected HTTP {stream_get.status} while reading public B62 stream route with GET"
        )

    stream_present, stream_probe_status, stream_probe_code = stream_route_probe(
        base_url=origin,
        poster=poster,
    )
    b14_stream_present, b14_stream_status = b14_auto_stream_route_probe(
        base_url=b14_origin,
        fetcher=fetcher,
    )
    return ParityResult(
        parity,
        stream_present,
        stream_get.status,
        stream_probe_status,
        stream_probe_code,
        b14_stream_present,
        b14_stream_status,
    )


def _render_bool(value: bool) -> str:
    return "true" if value else "false"


def emit(result: ParityResult) -> None:
    for name, value in result.asset_parity.items():
        rendered = _render_bool(value)
        print(f"{name}_PARITY={rendered}")
        print(f"B62_{name}_PARITY={rendered}")
    print(f"STREAM_ROUTE_PRESENT={_render_bool(result.stream_route_present)}")
    print(f"STREAM_ROUTE_GET_HTTP={result.stream_get_status}")
    print("STREAM_ROUTE_PROBE_METHOD=POST_INVALID")
    print(f"STREAM_ROUTE_PROBE_HTTP={result.stream_probe_status}")
    print(f"STREAM_ROUTE_PROBE_ERROR_CODE={result.stream_probe_error_code or 'none'}")
    print(f"B62_STREAM_ROUTE_PRESENT={_render_bool(result.stream_route_present)}")
    print(f"B62_STREAM_ROUTE_GET_HTTP={result.stream_get_status}")
    print(f"B62_STREAM_ROUTE_PROBE_HTTP={result.stream_probe_status}")
    print(
        f"B14_AUTO_STREAM_ROUTE_PRESENT={_render_bool(result.b14_auto_stream_route_present)}"
    )
    print(f"B14_AUTO_STREAM_ROUTE_GET_HTTP={result.b14_auto_stream_get_status}")
    print(
        f"DEPLOYED_PROGRESSIVE_SSE_SURFACE={'READY' if result.b62_ready else 'HOLD'}"
    )
    print(f"DEPLOYED_PROGRESSIVE_SSE_CHAIN={'READY' if result.ready else 'HOLD'}")
    print("HTTP_METHODS_USED=GET_PLUS_ONE_INVALID_POST")
    print("INVALID_ROUTE_PROBE_POSTS=1")
    print("CHAT_POSTS=0")
    print("VALID_CHAT_POSTS=0")
    print("REAL_PROVIDER_CALLS=0")
    print("QUOTA_MUTATION=0")
    print("HISTORY_MUTATION=0")

    summary = os.getenv("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n## B14 → B62 deployed progressive-SSE parity\n\n")
            handle.write("| Check | Result |\n|---|---|\n")
            for name, value in result.asset_parity.items():
                handle.write(f"| B62_{name}_PARITY | `{_render_bool(value)}` |\n")
            handle.write(
                f"| B62_STREAM_ROUTE_PRESENT | `{_render_bool(result.stream_route_present)}` |\n"
            )
            handle.write(f"| B62_STREAM_ROUTE_GET_HTTP | `{result.stream_get_status}` |\n")
            handle.write("| B62_STREAM_ROUTE_PROBE_METHOD | `POST_INVALID` |\n")
            handle.write(
                f"| B62_STREAM_ROUTE_PROBE_HTTP | `{result.stream_probe_status}` |\n"
            )
            handle.write(
                f"| B62_STREAM_ROUTE_PROBE_ERROR_CODE | `{result.stream_probe_error_code or 'none'}` |\n"
            )
            handle.write(
                "| B14_AUTO_STREAM_ROUTE_PRESENT | "
                f"`{_render_bool(result.b14_auto_stream_route_present)}` |\n"
            )
            handle.write(
                f"| B14_AUTO_STREAM_ROUTE_GET_HTTP | `{result.b14_auto_stream_get_status}` |\n"
            )
            handle.write(
                f"| DEPLOYED_PROGRESSIVE_SSE_SURFACE | `{'READY' if result.b62_ready else 'HOLD'}` |\n"
            )
            handle.write(
                f"| DEPLOYED_PROGRESSIVE_SSE_CHAIN | `{'READY' if result.ready else 'HOLD'}` |\n"
            )
            handle.write("| HTTP methods used | `GET + one invalid POST` |\n")
            handle.write("| Valid chat/provider calls | `0` |\n")
            handle.write("| Quota/history mutation | `0` |\n")


def main() -> int:
    try:
        base_url = normalized_base_url(os.getenv("B62_BASE_URL", ""), "B62_BASE_URL")
        b14_base_url = normalized_base_url(os.getenv("B14_BASE_URL", ""), "B14_BASE_URL")
        repo_root = Path(__file__).resolve().parents[2]
        result = audit(
            base_url=base_url,
            b14_base_url=b14_base_url,
            repo_root=repo_root,
        )
        emit(result)
        # Deployment lag is a truthful HOLD, not an audit failure. This keeps
        # unrelated source PRs mergeable while making cross-Worker drift visible.
        return 0
    except Exception as exc:
        print(f"B62_DEPLOYED_PARITY_ERROR={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
