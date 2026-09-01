from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from urllib.error import URLError

import pytest


def _load_module():
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / ".github/scripts/b62_cloudflare_deployed_parity.py"
    module_name = "b62_cloudflare_deployed_parity_contract"
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_assets(module, root: Path) -> dict[str, bytes]:
    bodies: dict[str, bytes] = {}
    for name, public_path, relative_path in module.ASSETS:
        body = f"// {name} exact\n".encode()
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        bodies[public_path] = body
    return bodies


def _fetcher(
    module,
    b62_base: str,
    b14_base: str,
    bodies: dict[str, bytes],
    *,
    b62_get_status=404,
    b62_get_allow="",
    b14_stream_status=405,
    b14_stream_allow="POST",
):
    def fetch(url: str):
        if url.startswith(b62_base):
            path = url.removeprefix(b62_base)
            if path == module.B62_STREAM_PATH:
                return module.HTTPResult(
                    b62_get_status,
                    {"allow": b62_get_allow},
                    b"b62 GET body must stay private",
                )
            if path in bodies:
                return module.HTTPResult(
                    200,
                    {"content-type": "application/javascript"},
                    bodies[path],
                )
        if url.startswith(b14_base):
            path = url.removeprefix(b14_base)
            if path == module.B14_AUTO_STREAM_PATH:
                return module.HTTPResult(
                    b14_stream_status,
                    {"allow": b14_stream_allow},
                    b"b14 route body must stay private",
                )
        return module.HTTPResult(404, {}, b"")

    return fetch


def _poster(module, *, status=422, error_code="invalid_request"):
    def post(url: str):
        if status == 422:
            body = json.dumps(
                {"error": {"code": error_code, "message": "bounded invalid probe"}}
            ).encode()
        else:
            body = b""
        return module.HTTPResult(status, {"content-type": "application/json"}, body)

    return post


def _audit(module, tmp_path, **overrides):
    b62_base = "https://padiem-chat.example.workers.dev"
    b14_base = "https://ai-revenue-korean-ai-platform.example.workers.dev"
    bodies = _write_assets(module, tmp_path)
    fetch_keys = {
        key: overrides.pop(key)
        for key in list(overrides)
        if key in {"b62_get_status", "b62_get_allow", "b14_stream_status", "b14_stream_allow"}
    }
    post_keys = {
        key: overrides.pop(key)
        for key in list(overrides)
        if key in {"status", "error_code"}
    }
    assert not overrides
    return module.audit(
        base_url=b62_base,
        b14_base_url=b14_base,
        repo_root=tmp_path,
        fetcher=_fetcher(module, b62_base, b14_base, bodies, **fetch_keys),
        poster=_poster(module, **post_keys),
    )


def test_exact_assets_b62_get_404_invalid_post_422_and_b14_405_make_chain_ready(tmp_path):
    module = _load_module()
    result = _audit(module, tmp_path)

    assert result.asset_parity == {
        "APP_JS": True,
        "SEARCH_SOURCES_JS": True,
        "RICH_RESPONSE_JS": True,
    }
    assert result.stream_route_present is True
    assert result.stream_get_status == 404
    assert result.stream_probe_status == 422
    assert result.stream_probe_error_code == "invalid_request"
    assert result.b14_auto_stream_route_present is True
    assert result.b14_auto_stream_get_status == 405
    assert result.b62_ready is True
    assert result.ready is True


def test_one_byte_browser_asset_drift_is_chain_hold_not_audit_failure(tmp_path):
    module = _load_module()
    b62_base = "https://padiem-chat.example.workers.dev"
    b14_base = "https://ai-revenue-korean-ai-platform.example.workers.dev"
    bodies = _write_assets(module, tmp_path)
    bodies["/app.js"] += b"x"

    result = module.audit(
        base_url=b62_base,
        b14_base_url=b14_base,
        repo_root=tmp_path,
        fetcher=_fetcher(module, b62_base, b14_base, bodies),
        poster=_poster(module),
    )

    assert result.asset_parity["APP_JS"] is False
    assert result.stream_route_present is True
    assert result.b14_auto_stream_route_present is True
    assert result.b62_ready is False
    assert result.ready is False


def test_404_b62_invalid_post_probe_is_hold(tmp_path):
    module = _load_module()
    result = _audit(module, tmp_path, status=404)

    assert result.stream_route_present is False
    assert result.stream_probe_status == 404
    assert result.b14_auto_stream_route_present is True
    assert result.ready is False


def test_404_b14_auto_stream_route_is_chain_hold(tmp_path):
    module = _load_module()
    result = _audit(
        module,
        tmp_path,
        b14_stream_status=404,
        b14_stream_allow="",
    )

    assert result.b62_ready is True
    assert result.b14_auto_stream_route_present is False
    assert result.b14_auto_stream_get_status == 404
    assert result.ready is False


def test_unexpected_b62_stream_get_status_fails_closed(tmp_path):
    module = _load_module()
    with pytest.raises(module.AuditError, match="unexpected HTTP 200"):
        _audit(module, tmp_path, b62_get_status=200)


def test_unexpected_b14_stream_get_status_fails_closed(tmp_path):
    module = _load_module()
    with pytest.raises(module.AuditError, match="unexpected HTTP 200"):
        _audit(module, tmp_path, b14_stream_status=200, b14_stream_allow="")


def test_b14_405_without_post_in_allow_fails_closed(tmp_path):
    module = _load_module()
    with pytest.raises(module.AuditError, match="without POST"):
        _audit(
            module,
            tmp_path,
            b14_stream_status=405,
            b14_stream_allow="GET, HEAD",
        )


def test_b62_invalid_post_requires_exact_invalid_request_signature(tmp_path):
    module = _load_module()
    with pytest.raises(module.AuditError, match="expected invalid_request"):
        _audit(module, tmp_path, error_code="streaming_unsupported")


def test_fetch_get_constructs_get_only():
    module = _load_module()
    observed = []

    class Response:
        status = 200
        headers = {"Content-Type": "application/javascript"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b"safe"

    def opener(request, timeout):
        observed.append((request.get_method(), request.full_url, request.data, timeout))
        return Response()

    result = module.fetch_get(
        "https://padiem-chat.example.workers.dev/app.js",
        opener=opener,
    )

    assert result.status == 200
    assert observed == [
        ("GET", "https://padiem-chat.example.workers.dev/app.js", None, 20)
    ]


def test_invalid_post_probe_is_empty_and_bounded():
    module = _load_module()
    observed = []

    class Response:
        status = 422
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return b'{"error":{"code":"invalid_request"}}'

    def opener(request, timeout):
        observed.append(
            (
                request.get_method(),
                request.full_url,
                request.data,
                request.headers.get("Content-type"),
                timeout,
            )
        )
        return Response()

    result = module.fetch_invalid_post(
        "https://padiem-chat.example.workers.dev/api/chat/stream",
        opener=opener,
    )

    assert result.status == 422
    assert observed == [
        (
            "POST",
            "https://padiem-chat.example.workers.dev/api/chat/stream",
            b"",
            "application/json",
            20,
        )
    ]


def test_network_failure_fails_get_and_invalid_post_closed():
    module = _load_module()

    def opener(request, timeout):
        raise URLError("offline")

    with pytest.raises(module.AuditError, match="network error"):
        module.fetch_get(
            "https://padiem-chat.example.workers.dev/app.js",
            opener=opener,
        )
    with pytest.raises(module.AuditError, match="network error"):
        module.fetch_invalid_post(
            "https://padiem-chat.example.workers.dev/api/chat/stream",
            opener=opener,
        )


def test_unexpected_public_asset_status_fails_closed(tmp_path):
    module = _load_module()
    b62_base = "https://padiem-chat.example.workers.dev"
    b14_base = "https://ai-revenue-korean-ai-platform.example.workers.dev"
    bodies = _write_assets(module, tmp_path)
    normal = _fetcher(module, b62_base, b14_base, bodies)

    def fetch(url: str):
        if url.endswith("/app.js"):
            return module.HTTPResult(503, {}, b"private upstream body")
        return normal(url)

    with pytest.raises(module.AuditError, match="unexpected HTTP 503"):
        module.audit(
            base_url=b62_base,
            b14_base_url=b14_base,
            repo_root=tmp_path,
            fetcher=fetch,
            poster=_poster(module),
        )


def test_emit_reports_method_aware_surface_and_chain_status(capsys):
    module = _load_module()
    result = module.ParityResult(
        {"APP_JS": True, "SEARCH_SOURCES_JS": True, "RICH_RESPONSE_JS": True},
        True,
        404,
        422,
        "invalid_request",
        False,
        404,
    )

    module.emit(result)
    output = capsys.readouterr().out

    assert "DEPLOYED_PROGRESSIVE_SSE_SURFACE=READY" in output
    assert "DEPLOYED_PROGRESSIVE_SSE_CHAIN=HOLD" in output
    assert "B62_APP_JS_PARITY=true" in output
    assert "STREAM_ROUTE_GET_HTTP=404" in output
    assert "STREAM_ROUTE_PROBE_METHOD=POST_INVALID" in output
    assert "STREAM_ROUTE_PROBE_HTTP=422" in output
    assert "STREAM_ROUTE_PROBE_ERROR_CODE=invalid_request" in output
    assert "B14_AUTO_STREAM_ROUTE_PRESENT=false" in output
    assert "INVALID_ROUTE_PROBE_POSTS=1" in output
    assert "VALID_CHAT_POSTS=0" in output
    assert "REAL_PROVIDER_CALLS=0" in output
    assert "QUOTA_MUTATION=0" in output
    assert "HISTORY_MUTATION=0" in output
    assert "private upstream body" not in output
    assert "b14 route body must stay private" not in output


def test_hold_result_exits_zero(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("B62_BASE_URL", "https://padiem-chat.example.workers.dev")
    monkeypatch.setenv(
        "B14_BASE_URL",
        "https://ai-revenue-korean-ai-platform.example.workers.dev",
    )
    monkeypatch.setattr(
        module,
        "audit",
        lambda **kwargs: module.ParityResult(
            {"APP_JS": False, "SEARCH_SOURCES_JS": False, "RICH_RESPONSE_JS": False},
            False,
            404,
            404,
            None,
            False,
            404,
        ),
    )
    monkeypatch.setattr(module, "emit", lambda result: None)

    assert module.main() == 0


def test_base_urls_are_bounded_to_bare_workers_dev_origins():
    module = _load_module()

    assert (
        module.normalized_base_url(
            "https://padiem-chat.example.workers.dev/",
            "B62_BASE_URL",
        )
        == "https://padiem-chat.example.workers.dev"
    )
    assert (
        module.normalized_base_url(
            "https://ai-revenue-korean-ai-platform.example.workers.dev/",
            "B14_BASE_URL",
        )
        == "https://ai-revenue-korean-ai-platform.example.workers.dev"
    )
    for invalid in (
        "http://padiem-chat.example.workers.dev",
        "https://user:pass@padiem-chat.example.workers.dev",
        "https://padiem-chat.example.workers.dev/path",
        "https://padiem-chat.example.workers.dev?x=1",
        "https://example.com",
    ):
        with pytest.raises(module.AuditError):
            module.normalized_base_url(invalid, "TEST_BASE_URL")


def test_public_parity_script_requires_no_credentials_and_only_empty_probe_post():
    module = _load_module()
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "CLOUDFLARE_API_TOKEN" not in source
    assert "OPENROUTER_API_KEY" not in source
    assert "BUSINESS14_PROVIDER_KEY" not in source
    assert 'method="GET"' in source
    assert 'method="POST"' in source
    assert 'data=b""' in source
    assert "invalid_request" in source
    assert module.B14_AUTO_STREAM_PATH in source
