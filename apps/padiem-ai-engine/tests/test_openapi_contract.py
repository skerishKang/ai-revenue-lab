"""Source-bound contract test for the Engine OpenAPI spec (#1976).

Network-free. The spec in ``openapi.json`` is NOT decorative: this test proves
it cannot drift from the real Engine HTTP contract in ``app/service.py``. If a
path, a required request field, or the request-body safety limit changes in
source, this test fails and the spec must be updated in the same change.

No Prometheus/Grafana/OTel is involved; this is the documentation-gap fix for
#1976 (the repository had zero API specs before this change).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.service import (
    EXECUTE_PATH,
    HEALTH_PATH,
    MAX_REQUEST_BODY_BYTES,
    _AGENT_REQUIRED,
    _TOP_LEVEL_REQUIRED,
)

_SPEC_PATH = Path(__file__).resolve().parents[1] / "openapi.json"

# Status codes the real handle()/execute_payload can emit. The spec must document
# every one of these for the execute route.
_EXPECTED_EXECUTE_STATUSES = {
    "400", "404", "405", "409", "413", "415", "422", "500", "502", "503", "504",
}


@pytest.fixture(scope="module")
def spec() -> dict:
    raw = _SPEC_PATH.read_text(encoding="utf-8")
    return json.loads(raw)


def test_spec_is_valid_openapi_3(spec: dict):
    assert spec["openapi"].startswith("3."), "spec must be OpenAPI 3.x"
    assert spec["info"]["title"]
    assert spec["paths"]


def test_spec_paths_match_engine_routes(spec: dict):
    assert set(spec["paths"].keys()) == {HEALTH_PATH, EXECUTE_PATH}


def test_health_only_declares_get(spec: dict):
    assert set(spec["paths"][HEALTH_PATH].keys()) == {"get"}
    responses = spec["paths"][HEALTH_PATH]["get"]["responses"]
    assert "200" in responses
    assert "405" in responses


def test_execute_only_declares_post(spec: dict):
    assert set(spec["paths"][EXECUTE_PATH].keys()) == {"post"}


def test_execute_request_body_is_required(spec: dict):
    post = spec["paths"][EXECUTE_PATH]["post"]
    assert post["requestBody"]["required"] is True


def test_execute_required_top_level_fields_match_source(spec: dict):
    execute_req = spec["components"]["schemas"]["ExecuteRequest"]
    assert set(execute_req["required"]) == set(_TOP_LEVEL_REQUIRED)


def test_execute_required_agent_fields_match_source(spec: dict):
    agent_req = spec["components"]["schemas"]["AgentSpec"]
    assert set(agent_req["required"]) == set(_AGENT_REQUIRED)


def test_execute_max_body_bytes_match_source(spec: dict):
    post = spec["paths"][EXECUTE_PATH]["post"]
    assert post["x-engine-max-body-bytes"] == MAX_REQUEST_BODY_BYTES


def test_execute_documents_every_emitted_status(spec: dict):
    responses = spec["paths"][EXECUTE_PATH]["post"]["responses"]
    documented = set(responses.keys())
    missing = _EXPECTED_EXECUTE_STATUSES - documented
    assert not missing, f"execute route omits status codes: {sorted(missing)}"


def test_every_error_response_uses_error_schema(spec: dict):
    error_ref = {"$ref": "#/components/schemas/ErrorResponse"}
    for path, methods in spec["paths"].items():
        for method in methods.values():
            for status, response in method["responses"].items():
                if status == "200":
                    continue
                content = response["content"]["application/json"]["schema"]
                assert content == error_ref, f"{path} {status} must use ErrorResponse"


def test_error_schema_shape(spec: dict):
    error = spec["components"]["schemas"]["ErrorResponse"]
    assert set(error["required"]) == {"ok", "error"}
    assert set(error["properties"]["error"]["required"]) == {"code", "message", "retryable"}


def test_health_200_reports_capability_posture(spec: dict):
    health = spec["components"]["schemas"]["Health200Response"]
    assert "capabilities" in health["required"]
    assert "b14_service_bound" in health["required"]
