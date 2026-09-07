"""Tests for the A11 Gmail tool_runtime production smoke script (#2010 / WO-10 ACT-1).

The script is loaded by path (same convention as
``test_a12_stream_replay_smoke_script.py``). Most cases use a mocked transport;
the two end-to-end cases drive the real ``urllib`` path against a loopback HTTP
server on 127.0.0.1, so headers, method and JSON body are proven for real.
Nothing here touches production, D1, or any provider.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import threading
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import pytest

APP_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_ROOT.parents[1]
SMOKE_PATH = APP_ROOT / "scripts" / "a11_gmail_tool_runtime_smoke.py"

spec = importlib.util.spec_from_file_location("a11_gmail_tool_runtime_smoke", SMOKE_PATH)
assert spec is not None and spec.loader is not None
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


HEALTH_OK = {
    "status": "ok",
    "capabilities": {"tool_runtime": "deferred"},
    "endpoints": [{"path": "/internal/v1/health", "method": "GET"}],
}


def _error(code: str) -> dict[str, object]:
    return {"ok": False, "error": {"code": code, "message": "probe"}}


# --- honest classification --------------------------------------------------


def test_require_env_skips_honestly(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(smoke, "CALLER_ID", ""), patch.object(smoke, "CALLER_SECRET", ""):
        assert smoke._require_env() is False
        _, err = capsys.readouterr()
        assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=SKIPPED_MISSING_SECRET" in err
        assert "SMOKE=SKIPPED_MISSING_SECRET" in err


@pytest.mark.parametrize(
    ("status", "code", "expected"),
    [
        (404, "not_found", smoke.ROUTE_UNAVAILABLE),
        (503, "tool_runtime_unavailable", smoke.RUNTIME_UNAVAILABLE),
        (503, "connector_grants_unavailable", smoke.RUNTIME_UNAVAILABLE),
        (403, "tool_not_registered", smoke.TOOL_NOT_ALLOWED),
        (403, "tool_agent_not_bound", smoke.TOOL_NOT_ALLOWED),
        (403, "tool_auth_scope_missing", smoke.TOOL_NOT_ALLOWED),
        (400, "tool_arguments_too_large", smoke.TOOL_CONTRACT_LIVE),
        (400, "invalid_tool_arguments", smoke.TOOL_CONTRACT_LIVE),
        (400, "invalid_tool_request", smoke.INVALID_REQUEST),
        (415, "unsupported_media_type", smoke.INVALID_REQUEST),
        (500, "engine_internal_error", smoke.UPSTREAM_UNEXPECTED),
        (502, None, smoke.UPSTREAM_UNEXPECTED),
        (200, None, smoke.UNEXPECTED),
    ],
)
def test_classify_maps_every_documented_class(status: int, code: str | None, expected: str) -> None:
    assert smoke.classify(status, code) == expected


def test_404_with_any_other_code_is_not_silently_treated_as_route_state() -> None:
    # Only the route-level not_found code may be classified ROUTE_UNAVAILABLE.
    assert smoke.classify(404, "tool_not_found") != smoke.ROUTE_UNAVAILABLE


# --- probe payload contract -------------------------------------------------


def test_probe_sends_only_the_four_allowed_wire_fields() -> None:
    captured: dict[str, object] = {}

    def _fake_request(*, method: str, path: str, body: dict[str, object] | None = None) -> tuple[int, dict]:
        captured["method"] = method
        captured["path"] = path
        captured["body"] = body
        return 404, _error("not_found")

    with patch.object(smoke, "_request", _fake_request), patch.object(smoke, "_failures", []):
        smoke.s1_canonical_gmail_probe()

    assert captured["method"] == "POST"
    assert captured["path"] == smoke.TOOL_EXECUTE_PATH
    body = captured["body"]
    assert isinstance(body, dict)
    assert set(body) == {"app_id", "agent_id", "tool_id", "arguments"}
    assert body["app_id"] == "b54-padiem-claw"
    assert body["agent_id"] == "agent:padiem:claw_mail_reader@1"
    assert body["tool_id"] == "tool:google:gmail.search_messages@1"


def test_probe_never_carries_credential_material() -> None:
    captured: dict[str, object] = {}

    def _fake_request(*, method: str, path: str, body: dict[str, object] | None = None) -> tuple[int, dict]:
        captured["body"] = body
        return 404, _error("not_found")

    with patch.object(smoke, "_request", _fake_request), patch.object(smoke, "_failures", []):
        smoke.s1_canonical_gmail_probe()

    serialised = json.dumps(captured["body"])
    for forbidden in ("refresh_token", "client_secret", "access_token", "client_id", "credential"):
        assert forbidden not in serialised


def test_oversized_argument_exceeds_the_core_ceiling_but_not_the_body_ceiling() -> None:
    arguments = {"query": smoke.OVERSIZED_ARGUMENT}
    size = len(json.dumps(arguments, separators=(",", ":")).encode("utf-8"))
    assert size > 65536  # MAX_TOOL_ARGUMENT_BYTES -> tool_arguments_too_large fires
    body = {
        "app_id": "b54-padiem-claw",
        "agent_id": "agent:padiem:claw_mail_reader@1",
        "tool_id": "tool:google:gmail.search_messages@1",
        "arguments": arguments,
    }
    assert len(json.dumps(body).encode("utf-8")) < 128 * 1024  # MAX_REQUEST_BODY_BYTES


# --- step behaviour ---------------------------------------------------------


def test_s1_records_route_unavailable_without_failing(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(smoke, "_request", return_value=(404, _error("not_found"))), patch.object(
        smoke, "_failures", []
    ):
        verdict = smoke.s1_canonical_gmail_probe()
    assert verdict == smoke.ROUTE_UNAVAILABLE
    assert smoke._failures == []
    assert "ROUTE_UNAVAILABLE" in capsys.readouterr().out


def test_s1_is_live_on_tool_arguments_too_large(capsys: pytest.CaptureFixture[str]) -> None:
    with patch.object(
        smoke, "_request", return_value=(400, _error("tool_arguments_too_large"))
    ), patch.object(smoke, "_failures", []):
        verdict = smoke.s1_canonical_gmail_probe()
    assert verdict == smoke.TOOL_CONTRACT_LIVE
    assert smoke._failures == []
    assert "provider never called" in capsys.readouterr().out


def test_s1_fails_when_the_tool_actually_executes() -> None:
    failures: list[str] = []
    with patch.object(smoke, "_request", return_value=(200, {"ok": True})), patch.object(
        smoke, "_failures", failures
    ):
        verdict = smoke.s1_canonical_gmail_probe()
    assert verdict == smoke.UNEXPECTED
    assert len(failures) == 1
    assert "must never reach the provider" in failures[0]


def test_s1_fails_on_unexpected_upstream_5xx() -> None:
    failures: list[str] = []
    with patch.object(smoke, "_request", return_value=(502, {})), patch.object(smoke, "_failures", failures):
        verdict = smoke.s1_canonical_gmail_probe()
    assert verdict == smoke.UPSTREAM_UNEXPECTED
    assert len(failures) == 1


def test_s2_requires_registry_rejection_when_runtime_is_live() -> None:
    failures: list[str] = []
    with patch.object(smoke, "_request", return_value=(403, _error("tool_not_registered"))), patch.object(
        smoke, "_failures", failures
    ):
        smoke.s2_unregistered_tool_probe(smoke.TOOL_CONTRACT_LIVE)
    assert failures == []


def test_s2_fails_if_an_unregistered_tool_is_accepted() -> None:
    failures: list[str] = []
    with patch.object(
        smoke, "_request", return_value=(400, _error("tool_arguments_too_large"))
    ), patch.object(smoke, "_failures", failures):
        smoke.s2_unregistered_tool_probe(smoke.TOOL_CONTRACT_LIVE)
    assert len(failures) == 1
    assert "unregistered tool" in failures[0]


def test_s2_accepts_consistency_with_a_deferred_s1() -> None:
    failures: list[str] = []
    with patch.object(
        smoke, "_request", return_value=(503, _error("tool_runtime_unavailable"))
    ), patch.object(smoke, "_failures", failures):
        smoke.s2_unregistered_tool_probe(smoke.RUNTIME_UNAVAILABLE)
    assert failures == []


def test_s3_requires_4xx_cross_app_isolation() -> None:
    failures: list[str] = []
    with patch.object(
        smoke, "_request", return_value=(403, _error("service_app_not_authorized"))
    ), patch.object(smoke, "_failures", failures):
        smoke.s3_cross_app_isolation()
    assert failures == []


def test_s3_fails_on_2xx_cross_app_answer() -> None:
    failures: list[str] = []
    with patch.object(smoke, "_request", return_value=(200, {"ok": True})), patch.object(
        smoke, "_failures", failures
    ):
        smoke.s3_cross_app_isolation()
    assert len(failures) == 1
    assert "not 4xx" in failures[0]


# --- end-to-end verdicts ----------------------------------------------------


def _run_main(responses: list[tuple[int, object]]) -> int:
    with patch.object(smoke, "CALLER_ID", "smoke-caller"), patch.object(
        smoke, "CALLER_SECRET", "smoke-secret-not-a-real-value"
    ), patch.object(smoke, "_request", side_effect=responses), patch.object(smoke, "_failures", []):
        return smoke.main()


def test_main_defers_honestly_when_route_is_not_wired(capsys: pytest.CaptureFixture[str]) -> None:
    rc = _run_main([(200, HEALTH_OK), (404, _error("not_found"))])
    assert rc == 0
    out = capsys.readouterr().out
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=DEFERRED" in out
    assert "REASON=ROUTE_NOT_WIRED" in out
    assert "ROUTE_AVAILABLE=0" in out
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=PASS" not in out


def test_main_defers_honestly_when_runtime_is_unbound(capsys: pytest.CaptureFixture[str]) -> None:
    rc = _run_main(
        [
            (200, HEALTH_OK),
            (503, _error("tool_runtime_unavailable")),
            (503, _error("tool_runtime_unavailable")),
            (403, _error("service_app_not_authorized")),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=DEFERRED" in out
    assert "REASON=TOOL_RUNTIME_UNAVAILABLE" in out
    assert "ROUTE_AVAILABLE=1" in out


def test_main_passes_when_the_tool_contract_is_live(capsys: pytest.CaptureFixture[str]) -> None:
    rc = _run_main(
        [
            (200, HEALTH_OK),
            (400, _error("tool_arguments_too_large")),
            (403, _error("tool_not_registered")),
            (403, _error("service_app_not_authorized")),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=PASS" in out
    assert "REAL_PROVIDER_CALLS=0" in out
    assert "ROWS_WRITTEN=0" in out
    assert "D1_MUTATION=0" in out
    assert "TOOL_REGISTRY_LIVE=PASS" in out
    assert "CROSS_APP=PASS" in out


def test_main_fails_on_unexpected_execution(capsys: pytest.CaptureFixture[str]) -> None:
    rc = _run_main([(200, HEALTH_OK), (200, {"ok": True})])
    assert rc == 1
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=FAIL" in capsys.readouterr().err


def test_main_fails_when_health_is_down(capsys: pytest.CaptureFixture[str]) -> None:
    rc = _run_main([(503, {})])
    assert rc == 1
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=FAIL (S0 gate)" in capsys.readouterr().err


# --- end-to-end over the real urllib path (loopback only) -------------------

_LOOPBACK_CALLER_ID = "loopback-caller"
_LOOPBACK_CALLER_SECRET = "loopback-secret-not-a-real-value"


def _start_loopback(
    responses: list[tuple[int, dict[str, object]]],
) -> tuple[str, list[dict[str, object]], Callable[[], None]]:
    """Serve canned responses on 127.0.0.1 and record every received request."""
    requests: list[dict[str, object]] = []
    remaining = list(responses)

    class _Handler(http.server.BaseHTTPRequestHandler):
        def _respond(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            requests.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": {key.lower(): value for key, value in self.headers.items()},
                    "body": body,
                }
            )
            status, payload = remaining.pop(0) if remaining else (500, {})
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self._respond()

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            self._respond()

        def log_message(self, *args: object) -> None:
            return

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def _stop() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    return f"http://127.0.0.1:{server.server_address[1]}", requests, _stop


def test_end_to_end_route_not_wired_over_real_urllib(capsys: pytest.CaptureFixture[str]) -> None:
    base_url, requests, stop = _start_loopback(
        [(200, HEALTH_OK), (404, _error("not_found"))]
    )
    try:
        with patch.object(smoke, "ENGINE_BASE_URL", base_url), patch.object(
            smoke, "CALLER_ID", _LOOPBACK_CALLER_ID
        ), patch.object(smoke, "CALLER_SECRET", _LOOPBACK_CALLER_SECRET), patch.object(
            smoke, "_failures", []
        ):
            rc = smoke.main()
    finally:
        stop()

    assert rc == 0
    out = capsys.readouterr().out
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=DEFERRED" in out
    assert "REASON=ROUTE_NOT_WIRED" in out
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=PASS" not in out

    assert [str(item["path"]) for item in requests] == [
        "/internal/v1/health",
        "/internal/v1/tools/execute",
    ]
    probe = requests[1]
    assert probe["method"] == "POST"
    headers = probe["headers"]
    assert isinstance(headers, dict)
    assert headers["user-agent"] == "padiem-a11-smoke/1.0 (+github-actions)"
    assert headers["x-padiem-engine-caller"] == _LOOPBACK_CALLER_ID
    assert headers["content-type"] == "application/json"
    # The caller secret travels in its own header and is never echoed anywhere.
    assert headers["x-padiem-engine-credential"] == _LOOPBACK_CALLER_SECRET
    raw_body = probe["body"]
    assert isinstance(raw_body, bytes)
    assert _LOOPBACK_CALLER_SECRET.encode("utf-8") not in raw_body
    assert set(json.loads(raw_body.decode("utf-8"))) == {
        "app_id",
        "agent_id",
        "tool_id",
        "arguments",
    }


def test_end_to_end_pass_over_real_urllib(capsys: pytest.CaptureFixture[str]) -> None:
    base_url, requests, stop = _start_loopback(
        [
            (200, HEALTH_OK),
            (400, _error("tool_arguments_too_large")),
            (403, _error("tool_not_registered")),
            (403, _error("service_app_not_authorized")),
        ]
    )
    try:
        with patch.object(smoke, "ENGINE_BASE_URL", base_url), patch.object(
            smoke, "CALLER_ID", _LOOPBACK_CALLER_ID
        ), patch.object(smoke, "CALLER_SECRET", _LOOPBACK_CALLER_SECRET), patch.object(
            smoke, "_failures", []
        ):
            rc = smoke.main()
    finally:
        stop()

    assert rc == 0
    out = capsys.readouterr().out
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=PASS" in out
    assert "REAL_PROVIDER_CALLS=0" in out
    # S1 canonical, S2 unregistered, S3 cross-app — in that order.
    assert [str(item["path"]) for item in requests[1:]] == ["/internal/v1/tools/execute"] * 3
    bodies = [json.loads(bytes(item["body"]).decode("utf-8")) for item in requests[1:]]
    assert bodies[0]["tool_id"] == "tool:google:gmail.search_messages@1"
    assert bodies[1]["tool_id"] == "tool:google:gmail.a11_smoke_unregistered@1"
    assert bodies[2]["app_id"] == "b62"


# --- source-level safety contract -------------------------------------------


def test_script_accepts_no_credential_arguments() -> None:
    source = SMOKE_PATH.read_text(encoding="utf-8")
    assert "argparse" not in source
    assert "sys.argv" not in source
    for forbidden in ("refresh_token", "client_secret", "access_token", "client_id", "oauth", "OAuth"):
        assert forbidden not in source


def test_script_uses_the_shared_smoke_identity_conventions() -> None:
    source = SMOKE_PATH.read_text(encoding="utf-8")
    assert '"User-Agent"' in source
    assert "padiem-a11-smoke/1.0" in source
    assert "x-padiem-engine-caller" in source
    assert "urllib.request" in source


def test_deploy_gate_workflow_runs_a11_between_a10_and_a12() -> None:
    workflow_path = (
        REPO_ROOT / ".github" / "workflows" / "b54-engine-production-deploy-gate.yml"
    )
    assert workflow_path.exists()
    content = workflow_path.read_text(encoding="utf-8")
    assert "a11_gmail_tool_runtime_smoke.py" in content
    assert "A11_GMAIL_TOOL_RUNTIME_SMOKE=PASS" in content
    names = [
        line.strip()
        for line in content.splitlines()
        if line.strip().startswith("- name: Run A")
    ]
    assert names == [
        "- name: Run A9 production idempotency smoke",
        "- name: Run A10 continuation fail-closed smoke",
        "- name: Run A11 Gmail tool_runtime smoke",
        "- name: Run A12 streaming idempotency replay smoke",
    ]
