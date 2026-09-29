from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "kilo_space_bunny_anonymous_probe.py"

spec = importlib.util.spec_from_file_location("kilo_space_bunny_anonymous_probe", SCRIPT)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def _ok(model: str = probe.UPSTREAM_MODEL, content: str = "OK") -> bytes:
    return json.dumps(
        {
            "id": "anon-probe",
            "model": model,
            "choices": [{"message": {"role": "assistant", "content": content}}],
        },
        separators=(",", ":"),
    ).encode()


def test_default_invocation_cannot_reach_network() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = probe.main([])
    assert rc == 1
    assert "DEFAULT_LIVE_EXECUTION=BLOCKED" in out.getvalue()


@pytest.mark.parametrize("modality", ["", "video", "IMAGE", "auto"])
def test_unknown_modality_fails_before_network(modality: str) -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = probe.main(["--authorized-live-run", f"--modality={modality}"])
    assert rc == 1
    assert "KILO_POST_COUNT=0" in out.getvalue()


def test_headers_are_always_anonymous_even_if_secret_env_exists(monkeypatch) -> None:
    monkeypatch.setenv("KILO_API_KEY", "secret-value")
    monkeypatch.setenv("PADIEM_KILO_API_KEY", "secret-value-2")
    headers = probe.canonical_headers()
    assert all(key.lower() != "authorization" for key in headers)
    assert "secret-value" not in repr(headers)


def test_text_probe_posts_once_and_emits_bounded_evidence() -> None:
    calls = []

    def transport(body, headers):
        calls.append((body, headers))
        return 200, _ok()

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = probe.run("text", transport=transport)

    assert rc == 0
    assert len(calls) == 1
    body, headers = calls[0]
    assert body["model"] == "stealth/space-bunny-alpha"
    assert body["messages"][0]["content"] == "Reply with the single word OK."
    assert all(key.lower() != "authorization" for key in headers)
    output = out.getvalue()
    assert "SPACE_BUNNY_ANON_TEXT=PASS" in output
    assert "REQUEST_AUTH_MODE=ANONYMOUS" in output
    assert "KILO_POST_COUNT=1" in output
    assert "NETWORK_RETRY_COUNT=0" in output
    assert "RAW_RESPONSE_OUTPUT=0" in output


def test_image_probe_reuses_synthetic_fixture_and_posts_once() -> None:
    calls = []

    def transport(body, headers):
        calls.append((body, headers))
        return 200, _ok()

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = probe.run("image", transport=transport)

    assert rc == 0
    assert probe.IMAGE_FIXTURE.is_file()
    assert len(probe.IMAGE_FIXTURE.read_bytes()) <= probe.MAX_IMAGE_BYTES
    body = calls[0][0]
    parts = body["messages"][0]["content"]
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
    output = out.getvalue()
    assert "SPACE_BUNNY_ANON_IMAGE=PASS" in output
    assert "IMAGE_ACCEPTED=YES" in output
    assert "RAW_IMAGE_OUTPUT=0" in output


def test_http_failure_is_bounded_and_never_echoes_raw_error() -> None:
    raw_secret = "PRIVATE_UPSTREAM_DETAIL"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = probe.run(
            "text",
            transport=lambda body, headers: (
                401,
                json.dumps({"error": {"code": "unauthorized", "message": raw_secret}}).encode(),
            ),
        )
    assert rc == 1
    output = out.getvalue()
    assert "SPACE_BUNNY_ANON_TEXT=FAIL_HTTP" in output
    assert "KILO_ANON_HTTP=401" in output
    assert "ERROR_CODE=unauthorized" in output
    assert raw_secret not in output
    assert "KILO_POST_COUNT=1" in output
    assert "NETWORK_RETRY_COUNT=0" in output


def test_noncanonical_200_fails_closed_without_raw_output() -> None:
    sentinel = "PRIVATE_RESPONSE"
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = probe.run(
            "text",
            transport=lambda body, headers: (
                200,
                json.dumps({
                    "model": probe.UPSTREAM_MODEL,
                    "choices": [{"message": {"content": ""}}],
                    "x": sentinel,
                }).encode(),
            ),
        )
    assert rc == 1
    assert sentinel not in out.getvalue()


def test_response_model_mismatch_is_visible_but_content_stays_private() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = probe.run(
            "text",
            transport=lambda body, headers: (
                200, _ok(model="different/model", content="PRIVATE_OK")
            ),
        )
    assert rc == 0
    output = out.getvalue()
    assert "RESPONSE_MODEL=different/model" in output
    assert "RESPONSE_MODEL_MATCH=NO" in output
    assert "PRIVATE_OK" not in output
