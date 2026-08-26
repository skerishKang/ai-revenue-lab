from __future__ import annotations

import importlib.util
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


def _fetcher(module, base: str, bodies: dict[str, bytes], *, stream_status=405, stream_allow="POST"):
    def fetch(url: str):
        assert url.startswith(base)
        path = url.removeprefix(base)
        if path == "/api/chat/stream":
            return module.HTTPResult(stream_status, {"allow": stream_allow}, b"not exposed")
        if path in bodies:
            return module.HTTPResult(200, {"content-type": "application/javascript"}, bodies[path])
        return module.HTTPResult(404, {}, b"")

    return fetch


def test_exact_asset_bytes_and_post_only_stream_route_are_ready(tmp_path):
    module = _load_module()
    base = "https://padiem-chat.example.workers.dev"
    bodies = _write_assets(module, tmp_path)

    result = module.audit(
        base_url=base,
        repo_root=tmp_path,
        fetcher=_fetcher(module, base, bodies),
    )

    assert result.asset_parity == {
        "APP_JS": True,
        "SEARCH_SOURCES_JS": True,
        "RICH_RESPONSE_JS": True,
    }
    assert result.stream_route_present is True
    assert result.stream_get_status == 405
    assert result.ready is True


def test_one_byte_browser_asset_drift_is_hold_not_audit_failure(tmp_path):
    module = _load_module()
    base = "https://padiem-chat.example.workers.dev"
    bodies = _write_assets(module, tmp_path)
    bodies["/app.js"] += b"x"

    result = module.audit(
        base_url=base,
        repo_root=tmp_path,
        fetcher=_fetcher(module, base, bodies),
    )

    assert result.asset_parity["APP_JS"] is False
    assert result.stream_route_present is True
    assert result.ready is False


def test_404_stream_probe_means_deployed_route_absent_and_hold(tmp_path):
    module = _load_module()
    base = "https://padiem-chat.example.workers.dev"
    bodies = _write_assets(module, tmp_path)

    result = module.audit(
        base_url=base,
        repo_root=tmp_path,
        fetcher=_fetcher(module, base, bodies, stream_status=404, stream_allow=""),
    )

    assert result.stream_route_present is False
    assert result.stream_get_status == 404
    assert result.ready is False


def test_fetch_get_constructs_get_only_and_never_posts():
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
        observed.append((request.get_method(), request.full_url, timeout))
        return Response()

    result = module.fetch_get(
        "https://padiem-chat.example.workers.dev/app.js",
        opener=opener,
    )

    assert result.status == 200
    assert observed == [
        ("GET", "https://padiem-chat.example.workers.dev/app.js", 20)
    ]


def test_network_failure_fails_the_audit_closed():
    module = _load_module()

    def opener(request, timeout):
        raise URLError("offline")

    with pytest.raises(module.AuditError, match="network error"):
        module.fetch_get(
            "https://padiem-chat.example.workers.dev/app.js",
            opener=opener,
        )


def test_unexpected_public_http_status_fails_closed(tmp_path):
    module = _load_module()
    base = "https://padiem-chat.example.workers.dev"
    bodies = _write_assets(module, tmp_path)

    def fetch(url: str):
        if url.endswith("/app.js"):
            return module.HTTPResult(503, {}, b"private upstream body")
        return _fetcher(module, base, bodies)(url)

    with pytest.raises(module.AuditError, match="unexpected HTTP 503"):
        module.audit(base_url=base, repo_root=tmp_path, fetcher=fetch)


def test_emit_never_prints_public_asset_bodies(capsys):
    module = _load_module()
    result = module.ParityResult(
        {"APP_JS": False, "SEARCH_SOURCES_JS": True, "RICH_RESPONSE_JS": True},
        True,
        405,
    )

    module.emit(result)
    output = capsys.readouterr().out

    assert "DEPLOYED_PROGRESSIVE_SSE_SURFACE=HOLD" in output
    assert "APP_JS_PARITY=false" in output
    assert "CHAT_POSTS=0" in output
    assert "REAL_PROVIDER_CALLS=0" in output
    assert "private upstream body" not in output


def test_hold_result_exits_zero(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("B62_BASE_URL", "https://padiem-chat.example.workers.dev")
    monkeypatch.setattr(
        module,
        "audit",
        lambda **kwargs: module.ParityResult(
            {"APP_JS": False, "SEARCH_SOURCES_JS": False, "RICH_RESPONSE_JS": False},
            False,
            404,
        ),
    )
    monkeypatch.setattr(module, "emit", lambda result: None)

    assert module.main() == 0


def test_base_url_is_bounded_to_bare_workers_dev_origin():
    module = _load_module()

    assert (
        module.normalized_base_url("https://padiem-chat.example.workers.dev/")
        == "https://padiem-chat.example.workers.dev"
    )
    for invalid in (
        "http://padiem-chat.example.workers.dev",
        "https://user:pass@padiem-chat.example.workers.dev",
        "https://padiem-chat.example.workers.dev/path",
        "https://padiem-chat.example.workers.dev?x=1",
        "https://example.com",
    ):
        with pytest.raises(module.AuditError):
            module.normalized_base_url(invalid)


def test_public_parity_script_requires_no_cloudflare_or_provider_credentials():
    module = _load_module()
    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "CLOUDFLARE_API_TOKEN" not in source
    assert "OPENROUTER_API_KEY" not in source
    assert "BUSINESS14_PROVIDER_KEY" not in source
    assert 'method="POST"' not in source
    assert 'method="GET"' in source
