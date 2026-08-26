#!/usr/bin/env python3
"""Read-only deployed streaming-chain parity audit for Padiem Chat.

The audit makes GET requests only. It compares the public B62 browser assets
against this checkout and probes both POST-only streaming route surfaces with
GET so no chat, model/provider, quota, D1, or Worker mutation can occur.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = "b62-deployed-parity/1.1"
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
    except URLError as exc:
        raise AuditError("network error while reading a public streaming surface") from exc
    except AuditError:
        raise
    except Exception as exc:
        raise AuditError("unexpected error while reading a public streaming surface") from exc


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


def _post_only_route_probe(
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


def stream_route_probe(
    *,
    base_url: str,
    fetcher: Callable[[str], HTTPResult] = fetch_get,
) -> tuple[bool, int]:
    return _post_only_route_probe(
        base_url=base_url,
        path=B62_STREAM_PATH,
        label="public B62 stream route",
        fetcher=fetcher,
    )


def b14_auto_stream_route_probe(
    *,
    base_url: str,
    fetcher: Callable[[str], HTTPResult] = fetch_get,
) -> tuple[bool, int]:
    return _post_only_route_probe(
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
    stream_present, stream_status = stream_route_probe(base_url=origin, fetcher=fetcher)
    b14_stream_present, b14_stream_status = b14_auto_stream_route_probe(
        base_url=b14_origin,
        fetcher=fetcher,
    )
    return ParityResult(
        parity,
        stream_present,
        stream_status,
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
    print(f"B62_STREAM_ROUTE_PRESENT={_render_bool(result.stream_route_present)}")
    print(f"B62_STREAM_ROUTE_GET_HTTP={result.stream_get_status}")
    print(
        f"B14_AUTO_STREAM_ROUTE_PRESENT={_render_bool(result.b14_auto_stream_route_present)}"
    )
    print(f"B14_AUTO_STREAM_ROUTE_GET_HTTP={result.b14_auto_stream_get_status}")
    print(
        f"DEPLOYED_PROGRESSIVE_SSE_SURFACE={'READY' if result.b62_ready else 'HOLD'}"
    )
    print(f"DEPLOYED_PROGRESSIVE_SSE_CHAIN={'READY' if result.ready else 'HOLD'}")
    print("HTTP_METHODS_USED=GET_ONLY")
    print("CHAT_POSTS=0")
    print("REAL_PROVIDER_CALLS=0")

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
            handle.write("| HTTP methods used | `GET only` |\n")
            handle.write("| Chat/provider calls | `0` |\n")


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
