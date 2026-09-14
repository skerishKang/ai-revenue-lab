#!/usr/bin/env python3
"""Static and behavioural contract tests for the #2503 credential-equivalence
diagnostic gate.

Run: python .github/tests/test_b54_engine_credential_equivalence_diagnostic_gate.py

These tests NEVER touch the network: the probe executes against a mocked
transport. They prove:

1. fixed constants match the deployed Engine auth oracle (path, headers,
   caller/app ids, request budget of exactly two);
2. the classifier accepts a request only on the 200
   completed_execution_not_found projection and maps error codes through a
   closed public allowlist (anything else is "unrecognized");
3. R1 presents the raw credential and R2 presents only its
   leading/trailing-whitespace-stripped form, in exactly two requests;
4. the emitted evidence is a closed vocabulary that never contains the
   credential plaintext, a hash, a length, a prefix/suffix, a response body,
   or exception text;
5. the disposition mapping distinguishes RAW_MATCH /
   BOUNDARY_WHITESPACE_MATCH / NEITHER_MATCH / UNEXPECTED;
6. the workflow is dispatch-gated, never accepts secret material through
   workflow_dispatch inputs, runs the live probe in environment: production
   behind exact-main and expected-served-version guards, and contains no
   deploy, secret-mutation, D1-write, provider, or Phase-A path.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github/scripts/b54_engine_credential_equivalence_diagnostic.py"
WORKFLOW = ROOT / ".github/workflows/b54-engine-credential-equivalence-diagnostic-gate.yml"

spec = importlib.util.spec_from_file_location("b54_cred_eq", SCRIPT)
assert spec and spec.loader
MODULE = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODULE)

SENTINEL = "b62-sentinel-cVal-WHITESPACE-  "  # trailing boundary whitespace
CANONICAL = SENTINEL.strip()


def _not_found_body(key: str) -> bytes:
    return json.dumps(
        {"ok": True, "replayed": False, "idempotency_key": key, "reason": MODULE.NOT_FOUND_REASON}
    ).encode("utf-8")


def _error_body(code: str) -> bytes:
    return json.dumps(
        {"ok": False, "error": {"code": code, "message": "should never be echoed", "retryable": False, "metadata": None}}
    ).encode("utf-8")


class Recorder:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("request budget exceeded")
        return self.responses.pop(0)


def presented_header(request, name: str):
    # urllib.Request.add_header stores keys capitalized; get_header does not.
    return request.headers.get(name.capitalize())


def run_probe(responses, credential=SENTINEL):
    recorder = Recorder(responses)
    with contextlib.redirect_stdout(io.StringIO()) as out:
        evidence = MODULE.probe(credential, transport=recorder)
    return evidence, recorder, out.getvalue()


# 1. constants match the deployed auth oracle


def test_constants_match_deployed_oracle() -> None:
    assert MODULE.REPLAY_PATH == "/internal/v1/idempotency/completed/replay"
    assert MODULE.CALLER_ID == "b54-p01-overlay-20260914-a1"
    assert MODULE.APP_ID == "b54-padiem-claw"
    assert MODULE.CALLER_ID_HEADER == "x-padiem-engine-caller"
    assert MODULE.CALLER_CREDENTIAL_HEADER == "x-padiem-engine-credential"
    assert MODULE.REQUEST_BUDGET_MAX == 2
    assert MODULE.ENGINE_BASE_URL == "https://engine.padiem.net"
    assert MODULE.DIAGNOSTIC_USER_AGENT == "padiem-credential-diagnostic/1.0 (+github-actions)"
    assert re.fullmatch(r"[0-9a-f]{64}", MODULE.FINGERPRINT)


def test_generated_key_matches_deployed_identifier_validator() -> None:
    import secrets as _secrets

    key = f"{MODULE.KEY_PREFIX}-{_secrets.token_hex(16)}"
    assert MODULE._IDEMPOTENCY_KEY_RE.fullmatch(key)
    assert key != f"{MODULE.KEY_PREFIX}-{_secrets.token_hex(16)}"


# 2. classifier semantics


def test_classifier_accepts_only_the_not_found_projection() -> None:
    ok = MODULE.classify_response(200, _not_found_body("k"))
    assert ok["accepted"] is True and ok["error_code"] == "none" and ok["http_class"] == "2xx"
    for status, body in (
        (200, _error_body("not_found")),
        (200, b'{"ok": true, "replayed": true, "idempotency_key": "k"}'),
        (200, b"not json"),
        (200, b""),
    ):
        assert MODULE.classify_response(status, body)["accepted"] is False


def test_error_codes_pass_through_the_closed_allowlist_only() -> None:
    projected = MODULE.classify_response(401, _error_body("service_authentication_failed"))
    assert projected["error_code"] == "service_authentication_failed"
    assert projected["accepted"] is False
    injected = MODULE.classify_response(401, _error_body("leaks: " + SENTINEL))
    assert injected["error_code"] == "unrecognized"
    assert MODULE.classify_response(404, _error_body("not_found"))["error_code"] == "not_found"
    assert MODULE.classify_response(503, _error_body("idempotency_unavailable"))["error_code"] == "idempotency_unavailable"


# 3. two-request semantics: raw then stripped


def test_r1_raw_r2_stripped_exactly_two_requests() -> None:
    evidence, recorder, _ = run_probe([(200, _not_found_body("k")), (200, _not_found_body("k"))])
    assert len(recorder.requests) == 2
    r1_cred = presented_header(recorder.requests[0], MODULE.CALLER_CREDENTIAL_HEADER)
    r2_cred = presented_header(recorder.requests[1], MODULE.CALLER_CREDENTIAL_HEADER)
    assert r1_cred == SENTINEL
    assert r2_cred == CANONICAL
    assert r1_cred != r2_cred
    for request in recorder.requests:
        assert presented_header(request, MODULE.CALLER_ID_HEADER) == MODULE.CALLER_ID
        assert request.full_url == MODULE.ENGINE_BASE_URL + MODULE.REPLAY_PATH
        assert request.get_method() == "POST"
        assert request.data is not None
        payload = json.loads(request.data.decode("utf-8"))
        assert payload["app_id"] == MODULE.APP_ID
        assert payload["request_fingerprint"] == MODULE.FINGERPRINT
        assert MODULE._IDEMPOTENCY_KEY_RE.fullmatch(payload["idempotency_key"])
    # both requests share one fresh key so the pair is directly comparable
    keys = {json.loads(r.data.decode("utf-8"))["idempotency_key"] for r in recorder.requests}
    assert len(keys) == 1
    assert evidence["REQUESTS_ISSUED"] == "2"


def test_budget_is_two_requests_max() -> None:
    # Even when more canned responses exist, the probe must stop at two.
    recorder = Recorder([(200, _not_found_body("k"))] * 5)
    MODULE.probe(SENTINEL, transport=recorder)
    assert len(recorder.requests) == 2
    assert len(recorder.responses) == 3


# 3b. explicit diagnostic User-Agent (edge UA differential hotfix)


def test_requests_carry_explicit_diagnostic_user_agent() -> None:
    _, recorder, _ = run_probe([(200, _not_found_body("k")), (200, _not_found_body("k"))])
    assert len(recorder.requests) == 2
    for request in recorder.requests:
        ua = presented_header(request, "User-Agent")
        assert ua == MODULE.DIAGNOSTIC_USER_AGENT
        assert not ua.startswith("Python-urllib")


def test_user_agent_convention_and_request_shape_unchanged() -> None:
    assert re.fullmatch(
        r"padiem-[a-z0-9-]+/1\.0 \(\+github-actions\)", MODULE.DIAGNOSTIC_USER_AGENT
    )
    request = MODULE.build_request(MODULE.ENGINE_BASE_URL, SENTINEL, "b54-cred-eq-diag-k")
    # The UA is declared at construction time, so the opener never falls
    # back to the Python-urllib signature that the edge blocks.
    assert presented_header(request, "User-Agent") == MODULE.DIAGNOSTIC_USER_AGENT
    assert request.get_method() == "POST"
    assert request.full_url == MODULE.ENGINE_BASE_URL + MODULE.REPLAY_PATH
    assert presented_header(request, "Content-Type") == "application/json"
    assert presented_header(request, "Accept") == "application/json"
    assert presented_header(request, MODULE.CALLER_ID_HEADER) == MODULE.CALLER_ID
    assert presented_header(request, MODULE.CALLER_CREDENTIAL_HEADER) == SENTINEL


# 4/5. dispositions and bounded evidence


def test_disposition_raw_match() -> None:
    evidence, _, _ = run_probe([(200, _not_found_body("k")), (401, _error_body("service_authentication_failed"))])
    assert evidence["DISPOSITION"] == "RAW_MATCH"
    assert evidence["RAW_ACCEPTED"] == "YES"


def test_disposition_boundary_whitespace_match() -> None:
    evidence, _, _ = run_probe([(401, _error_body("service_authentication_failed")), (200, _not_found_body("k"))])
    assert evidence["DISPOSITION"] == "BOUNDARY_WHITESPACE_MATCH"
    assert evidence["RAW_ACCEPTED"] == "NO"
    assert evidence["STRIPPED_ACCEPTED"] == "YES"


def test_disposition_neither_match() -> None:
    evidence, _, _ = run_probe(
        [(401, _error_body("service_authentication_failed")), (401, _error_body("service_authentication_failed"))]
    )
    assert evidence["DISPOSITION"] == "NEITHER_MATCH"


def test_disposition_unexpected_on_non_auth_divergence() -> None:
    for pair in (
        [(503, _error_body("idempotency_unavailable")), (401, _error_body("service_authentication_failed"))],
        [(401, _error_body("service_authentication_failed")), (403, _error_body("service_app_not_authorized"))],
        [(0, b""), (0, b"")],
    ):
        evidence, _, _ = run_probe(pair)
        assert evidence["DISPOSITION"] == "UNEXPECTED", pair


def test_local_transport_fault_is_bounded_and_never_leaks_exception_text() -> None:
    def exploding_transport(request):
        raise RuntimeError("boom " + SENTINEL)

    with contextlib.redirect_stdout(io.StringIO()) as out:
        evidence = MODULE.probe(SENTINEL, transport=exploding_transport)
    assert evidence["R1_ERROR_CODE"] == "transport_blocked"
    assert evidence["R1_HTTP_CLASS"] == "blocked"
    assert evidence["DISPOSITION"] == "UNEXPECTED"
    assert "boom" not in out.getvalue()


# 6. no secret material in any emitted evidence


def test_rendered_evidence_never_contains_secret_material() -> None:
    evidence, _, _ = run_probe([(401, _error_body("service_authentication_failed")), (200, _not_found_body("k"))])
    rendered = MODULE.render(evidence)
    assert SENTINEL not in rendered
    assert CANONICAL not in rendered
    assert "should never be echoed" not in rendered
    for line in rendered.splitlines():
        assert re.fullmatch(
            r"^(R[12]_HTTP_STATUS=[0-9]{1,3}|R[12]_HTTP_CLASS=([1-5]xx|blocked)"
            r"|R[12]_ERROR_CODE=(none|unrecognized|transport_blocked|service_authentication_failed"
            r"|service_identity_unavailable|service_app_not_authorized|invalid_request|invalid_json"
            r"|unsupported_media_type|request_too_large|method_not_allowed|not_found|idempotency_unavailable)"
            r"|RAW_ACCEPTED=(YES|NO)|STRIPPED_ACCEPTED=(YES|NO)"
            r"|DISPOSITION=(RAW_MATCH|BOUNDARY_WHITESPACE_MATCH|NEITHER_MATCH|UNEXPECTED)"
            r"|REQUESTS_ISSUED=[0-9]|REQUEST_BUDGET_MAX=2|SECRET_VALUE_OUTPUT=0|SECRET_HASH_OUTPUT=0"
            r"|SECRET_LENGTH_OUTPUT=0|SECRET_PREFIX_SUFFIX_OUTPUT=0|RAW_REGISTRY_OUTPUT=0|PROVIDER_CALL=0"
            r"|D1_WRITE=0|DEPLOY=0|SECRET_MUTATION=0|PHASE_A=0|PRODUCTION_MUTATION=0)$",
            line,
        ), line
    # no line encodes a length or hash of the credential
    assert not re.search(r"=[0-9a-f]{16,}", rendered)


def test_rendered_evidence_key_cardinality_is_exactly_one() -> None:
    # Regression (#2507, run 34775820262): REQUESTS_ISSUED was emitted twice
    # (EVIDENCE_ORDER and SAFETY_MARKERS), so the workflow's exactly-one count
    # guard aborted the probe job before any evidence was echoed.
    evidence, _, _ = run_probe(
        [(401, _error_body("service_authentication_failed")), (200, _not_found_body("k"))]
    )
    rendered = MODULE.render(evidence)
    keys = [line.split("=", 1)[0] for line in rendered.splitlines()]
    assert len(keys) == len(set(keys)), f"duplicate evidence keys: {keys}"
    assert keys.count("REQUESTS_ISSUED") == 1
    assert keys == list(MODULE.EVIDENCE_ORDER) + [name for name, _ in MODULE.SAFETY_MARKERS]
    requests_line = [line for line in rendered.splitlines() if line.startswith("REQUESTS_ISSUED=")]
    assert len(requests_line) == 1
    assert re.fullmatch(r"REQUESTS_ISSUED=[0-2]", requests_line[0]), requests_line[0]
    assert requests_line[0] == f"REQUESTS_ISSUED={evidence['REQUESTS_ISSUED']}"
    assert SENTINEL not in rendered
    assert CANONICAL not in rendered


def test_cli_fails_closed_without_consuming_budget_on_empty_env() -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    old = os.environ.copy()
    os.environ.pop("B54_TEST_CRED", None)
    try:
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = MODULE.main(["--credential-env", "B54_TEST_CRED"])
    finally:
        os.environ.clear()
        os.environ.update(old)
    assert status == 1
    assert "credential_env_empty" in stderr.getvalue()
    assert "REQUESTS_ISSUED=0" in stderr.getvalue()
    assert stdout.getvalue() == ""


def test_cli_rejects_unsafe_env_name() -> None:
    stdout, stderr = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        status = MODULE.main(["--credential-env", "not/an/env"])
    assert status == 2
    assert stdout.getvalue() == ""


# 7. static workflow contract


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_workflow_never_accepts_secret_material_in_inputs() -> None:
    text = _workflow_text()
    inputs_block = text.split("\n  workflow_dispatch:\n", 1)[1].split("\npermissions:\n", 1)[0]
    assert "secrets." not in inputs_block
    assert "${{ secrets" not in inputs_block
    assert "CALLER_SECRET: ${{ secrets.B62_P01_ENGINE_CREDENTIAL }}" in text
    # the credential env is attached ONLY to the production probe job
    probe_job = text.split("\n  credential-equivalence-probe:\n", 1)[1]
    assert "environment: production" in probe_job
    assert "CALLER_SECRET" in probe_job


def test_workflow_structure_guards() -> None:
    text = _workflow_text()
    assert "environment: production" in text
    assert "RUN_B54_ENGINE_CREDENTIAL_EQUIVALENCE_PROBE" in text
    assert "EXPECTED_SERVED_VERSION_GUARD=PASS" in text
    assert "b54_engine_served_version_guard.py" in text
    assert "EXACT_MAIN_GUARD=PASS" in text
    assert "LIVE_PROBE_EXECUTED=NO" in text
    assert "CLOSED_OUTPUT_CONTRACT" in text
    # the PR trigger only ever runs the static contract tests
    trigger_block = text.split("\non:\n", 1)[1].split("\npermissions:\n", 1)[0]
    assert "pull_request:" in trigger_block
    assert "credential_equivalence_diagnostic" in trigger_block
    assert "apply" not in trigger_block
    # dispatch jobs are mode-gated; the probe needs the version preflight
    assert "inputs.mode == 'credential_equivalence_probe'" in text
    assert "needs: [source-contract, served-version-preflight]" in text


def test_workflow_has_no_mutation_or_forbidden_request_path() -> None:
    text = _workflow_text()
    lowered = text.lower()
    for forbidden in (
        "wrangler",
        "-x put",
        "-x post",
        "-x delete",
        "secrets put",
        "d1 execute",
        "rollback",
        "deploy --",
        "pull_request_target",
        "workflow_write",
        "contents: write",
    ):
        assert forbidden not in lowered, forbidden
    # only GET reads against the Cloudflare API are present (deployments and
    # version detail); the deployments READ endpoint is legitimate.
    assert "workers/scripts/${engine_worker}/deployments" in lowered
    assert lowered.count("curl") == 2


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"B54_CREDENTIAL_EQUIVALENCE_GATE_TESTS=PASS ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
