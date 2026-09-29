"""Source-contract tests for the B66 Space Bunny image canary (#3212).

No test performs network I/O. The live harness is driven through synthetic
transports and the committed F02 fixture only.
"""

from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "b66_space_bunny_image_canary.py"
WORKFLOW = ROOT / ".github" / "workflows" / "b66-space-bunny-image-canary.yml"

spec = importlib.util.spec_from_file_location("b66_space_bunny_image_canary", SCRIPT)
assert spec is not None and spec.loader is not None
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)


def _json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _health() -> bytes:
    return _json({"business14": {"provider_mode": "live"}})


def _models(*, image: bool = True, route_ok: bool = True) -> bytes:
    return _json(
        {
            "registered_routes": [
                {
                    "id": canary.MODEL_ID,
                    "provider_id": canary.PROVIDER_ID if route_ok else "wrong",
                    "upstream_model": canary.UPSTREAM_MODEL,
                    "explicit_only": True,
                }
            ],
            "catalog": [
                {
                    "id": canary.MODEL_ID,
                    "tags": ["alpha", "chat", "coding", "free"]
                    + (["image"] if image else []),
                }
            ],
        }
    )


def _chat(*, facts=None, fallback=False, attempts=1) -> bytes:
    if facts is None:
        facts = dict(canary.EXPECTED)
    return _json(
        {
            "model": canary.UPSTREAM_MODEL,
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": json.dumps(facts, ensure_ascii=False),
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 10,
                "total_tokens": 20,
            },
            "business14": {
                "provider_mode": "live",
                "mode": "live",
                "provider": canary.PROVIDER_NAME,
                "selected_provider": canary.PROVIDER_NAME,
                "model_route": canary.MODEL_ID,
                "selected_model": canary.MODEL_ID,
                "upstream_model": canary.UPSTREAM_MODEL,
                "selected_upstream_model": canary.UPSTREAM_MODEL,
                "actual_response_model": canary.UPSTREAM_MODEL,
                "route_mode": "manual",
                "fallback_allowed": False,
                "fallback_used": fallback,
                "attempt_count": attempts,
                "route_evidence_status": "live_verified",
            },
        }
    )


def _happy_transport(calls):
    def transport(method, path, body):
        calls.append((method, path, body))
        if path == canary.HEALTH_PATH:
            return 200, _health()
        if path == canary.MODELS_PATH:
            return 200, _models()
        if path == canary.CHAT_PATH:
            return 200, _chat()
        raise AssertionError(path)

    return transport


def test_constants_pin_exact_space_bunny_route_and_single_call() -> None:
    assert canary.MODEL_ID == "kilo/stealth-space-bunny-alpha"
    assert canary.UPSTREAM_MODEL == "stealth/space-bunny-alpha"
    assert canary.PROVIDER_ID == "kilo"
    assert canary.MAX_PROVIDER_CALLS == 1
    assert canary.RETRY == 0
    assert canary.FALLBACK == 0
    assert canary.FIXTURE_SHA256 == "af9f48578b79dc9d712e695079e4b0fd44a02916f12007c14429593173432ba4"


def test_body_is_manual_image_request_with_no_b66_top_level_metadata() -> None:
    body = canary.canonical_chat_body(canary._fixture_bytes())
    assert set(body) == {"model", "messages", "stream", "business14"}
    assert body["model"] == canary.MODEL_ID
    assert body["stream"] is False
    assert "b66" not in body
    assert body["business14"] == {
        "required_capabilities": ["image"],
        "allow_external_fallback": False,
        "max_attempts": 1,
    }
    content = body["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_default_execution_is_blocked_and_makes_zero_calls() -> None:
    calls = []

    def transport(method, path, body):
        calls.append((method, path, body))
        raise AssertionError("network must not run")

    out = io.StringIO()
    with redirect_stdout(out):
        rc = canary.run(transport=transport, authorized=False)
    assert rc == 2
    assert calls == []
    text = out.getvalue()
    assert "DEFAULT_LIVE_EXECUTION=BLOCKED" in text
    assert "B14_CHAT_POST_COUNT=0" in text


def test_success_reads_real_f02_facts_with_exactly_one_post() -> None:
    calls = []
    out = io.StringIO()
    with redirect_stdout(out):
        rc = canary.run(transport=_happy_transport(calls), authorized=True)
    assert rc == 0
    assert [(m, p) for m, p, _ in calls] == [
        ("GET", canary.HEALTH_PATH),
        ("GET", canary.MODELS_PATH),
        ("POST", canary.CHAT_PATH),
    ]
    assert sum(1 for m, _, _ in calls if m == "POST") == 1
    sent = calls[-1][2]
    assert sent["model"] == canary.MODEL_ID
    assert sent["business14"]["allow_external_fallback"] is False
    assert sent["business14"]["max_attempts"] == 1
    text = out.getvalue()
    assert "B66_SPACE_BUNNY_IMAGE_CANARY=PASS" in text
    assert "F02_VISUAL_FACTS=PASS" in text
    assert "B14_CHAT_POST_COUNT=1" in text
    assert "NETWORK_RETRY_COUNT=0" in text
    assert "FALLBACK=0" in text


@pytest.mark.parametrize(
    "key,bad",
    [
        ("quote_number", "Q-WRONG"),
        ("recipient", "다른회사"),
        ("first_item", "다른품목"),
        ("first_quantity", "99"),
        ("first_unit_price", "123"),
    ],
)
def test_wrong_visual_fact_is_failure(key, bad) -> None:
    calls = []

    def transport(method, path, body):
        calls.append((method, path, body))
        if path == canary.HEALTH_PATH:
            return 200, _health()
        if path == canary.MODELS_PATH:
            return 200, _models()
        facts = dict(canary.EXPECTED)
        facts[key] = bad
        return 200, _chat(facts=facts)

    out = io.StringIO()
    with redirect_stdout(out):
        rc = canary.run(transport=transport, authorized=True)
    assert rc == 7
    assert "FAIL_VISUAL_FACTS" in out.getvalue()
    assert sum(1 for m, _, _ in calls if m == "POST") == 1


def test_route_or_image_capability_failure_happens_before_post() -> None:
    for models_raw, expected in [
        (_models(route_ok=False), "FAIL_ROUTE_IDENTITY"),
        (_models(image=False), "FAIL_IMAGE_CAPABILITY"),
    ]:
        calls = []

        def transport(method, path, body, models_raw=models_raw):
            calls.append((method, path, body))
            if path == canary.HEALTH_PATH:
                return 200, _health()
            if path == canary.MODELS_PATH:
                return 200, models_raw
            raise AssertionError("POST must not happen")

        out = io.StringIO()
        with redirect_stdout(out):
            rc = canary.run(transport=transport, authorized=True)
        assert rc == 5
        assert expected in out.getvalue()
        assert all(method != "POST" for method, _, _ in calls)


def test_fallback_or_second_attempt_is_failure() -> None:
    for fallback, attempts in [(True, 1), (False, 2)]:
        calls = []

        def transport(method, path, body, fallback=fallback, attempts=attempts):
            calls.append((method, path, body))
            if path == canary.HEALTH_PATH:
                return 200, _health()
            if path == canary.MODELS_PATH:
                return 200, _models()
            return 200, _chat(fallback=fallback, attempts=attempts)

        out = io.StringIO()
        with redirect_stdout(out):
            rc = canary.run(transport=transport, authorized=True)
        assert rc == 6
        assert "FAIL_ROUTE_EVIDENCE" in out.getvalue()


def test_non_json_answer_fails_without_printing_private_response() -> None:
    secret = "PRIVATE-SYNTHETIC-CONTENT"

    def transport(method, path, body):
        if path == canary.HEALTH_PATH:
            return 200, _health()
        if path == canary.MODELS_PATH:
            return 200, _models()
        payload = json.loads(_chat().decode("utf-8"))
        payload["choices"][0]["message"]["content"] = secret
        return 200, _json(payload)

    out = io.StringIO()
    with redirect_stdout(out):
        rc = canary.run(transport=transport, authorized=True)
    assert rc == 6
    text = out.getvalue()
    assert "answer_not_json" in text
    assert secret not in text
    assert "RAW_RESPONSE_CONTENT_OUTPUT=0" in text


def test_workflow_is_dispatch_only_for_live_job_and_exact_main_guarded() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "pull_request:" in text
    assert "RUN_B66_SPACE_BUNNY_IMAGE_CANARY_ONCE" in text
    assert "github.event_name == 'workflow_dispatch'" in text
    assert "git rev-parse origin/main" in text
    assert "resolve_served_version_id" in text
    assert "B14_DEPLOY=0" in text
    assert "PRODUCTION_MUTATION=0" in text
    assert "python .github/scripts/b66_space_bunny_image_canary.py --authorized-live-run" in text
