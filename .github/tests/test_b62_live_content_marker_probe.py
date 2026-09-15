"""B62 live-content #2124 marker probe contract tests (#2548, SOURCE-ONLY)."""
from __future__ import annotations

import importlib.util
import io
import json
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / ".github" / "scripts" / "b62_live_content_marker_probe.py"
WORKFLOW = ROOT / ".github" / "workflows" / "b62-live-content-marker-gate.yml"

ACTIVE = "c2468c5d-73e1-41fb-9408-565f871a4ad8"
OTHER = "cc9f8601-d3ab-4e48-ae4d-249f4d6f090c"
SECRET_ETAG = "etag-value-must-never-be-printed-1234"
SECRET_AUTHOR_EMAIL = "author-email-must-never-be-printed@example.com"
SECRET_AUTHOR_ID = "author-id-must-never-be-printed"
MAX_BYTES = 1024

MARKER_UNSUPPORTED = b"Business 14 Service Binding returned an unsupported stream chunk."
MARKER_MEMORYVIEW = b"memoryview(value).tobytes()"
MARKER_BYTES_VALUE = b"return bytes(value)"


def _load_helper():
    spec = importlib.util.spec_from_file_location("b62_live_content_marker_probe", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _deployments(version_id=ACTIVE, percentage=100):
    return {
        "success": True,
        "result": {
            "deployments": [
                {"versions": [{"version_id": version_id, "percentage": percentage}]},
                {"versions": [{"version_id": OTHER, "percentage": 100}]},
            ]
        },
    }


def _detail(etag=SECRET_ETAG, last_deployed_from=None, **extra):
    script = {"etag": etag}
    if last_deployed_from is not None:
        script["last_deployed_from"] = last_deployed_from
    result = {"resources": {"script": script}}
    result.update(extra)
    return {"success": True, "result": result}


def _full_content():
    return b"# worker\n" + MARKER_MEMORYVIEW + b"\n" + MARKER_BYTES_VALUE + b"\n" + MARKER_UNSUPPORTED + b"\n"


def _probe(helper, **overrides):
    kwargs = {
        "deployments_pre_payload": _deployments(),
        "deployments_post_payload": _deployments(),
        "expected_active_version": ACTIVE,
        "version_detail_payload": _detail(),
        "content_bytes": _full_content(),
        "max_content_bytes": MAX_BYTES,
    }
    kwargs.update(overrides)
    return helper.probe_live_content(**kwargs)


def test_all_markers_present_yields_pass_with_exact_vocabulary(tmp_path):
    helper = _load_helper()
    dep_pre = tmp_path / "deployments-pre.json"
    dep_post = tmp_path / "deployments-post.json"
    detail = tmp_path / "detail.json"
    detail_post = tmp_path / "detail-post.json"
    content = tmp_path / "content.bin"
    dep_pre.write_bytes(json.dumps(_deployments()).encode("utf-8"))
    dep_post.write_bytes(json.dumps(_deployments()).encode("utf-8"))
    detail.write_bytes(json.dumps(
        _detail(last_deployed_from="wrangler-4", metadata={"source": "wrangler"})
    ).encode("utf-8"))
    detail_post.write_bytes(json.dumps(_detail()).encode("utf-8"))
    content.write_bytes(_full_content())
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = helper.main([
            "--deployments-pre", str(dep_pre),
            "--deployments-post", str(dep_post),
            "--expected-active-version", ACTIVE,
            "--version-detail", str(detail),
            "--version-detail-post", str(detail_post),
            "--content", str(content),
            "--max-content-bytes", str(MAX_BYTES),
        ])
    assert rc == 0
    assert out.getvalue().splitlines() == [
        f"ACTIVE_VERSION={ACTIVE}",
        "ACTIVE_VERSION_MATCH=PASS",
        "SCRIPT_IDENTITY_PRESENT=PASS",
        "LIVE_CONTENT_FETCH=PASS",
        "LIVE_CONTENT_SIZE_BOUNDED=PASS",
        "MARKER_UNSUPPORTED_STREAM_CHUNK=PRESENT",
        "MARKER_MEMORYVIEW_TOBYTES=PRESENT",
        "MARKER_BYTES_VALUE=PRESENT",
        "PR2124_LIVE_MARKERS=PASS",
        "VERSION_METADATA_SOURCE=wrangler",
        "SCRIPT_LAST_DEPLOYED_FROM=wrangler-4",
        "RAW_SCRIPT_CONTENT_OUTPUT=0",
        "RAW_SCRIPT_ETAG_OUTPUT=0",
        "SECRET_VALUE_OUTPUT=0",
        "PRODUCTION_MUTATION=0",
    ]
    combined = out.getvalue() + err.getvalue()
    assert SECRET_ETAG not in combined
    assert b"unsupported stream chunk" not in combined.encode("utf-8")


def test_any_marker_absent_is_inconclusive_not_failure():
    helper = _load_helper()
    verdict = _probe(
        helper,
        content_bytes=b"x" + MARKER_MEMORYVIEW + b"y" + MARKER_BYTES_VALUE,
    )
    assert verdict["MARKER_UNSUPPORTED_STREAM_CHUNK"] == "ABSENT"
    assert verdict["MARKER_MEMORYVIEW_TOBYTES"] == "PRESENT"
    assert verdict["MARKER_BYTES_VALUE"] == "PRESENT"
    assert verdict["PR2124_LIVE_MARKERS"] == "INCONCLUSIVE"
    assert verdict["PR2124_LIVE_MARKERS"] != "FAIL"


def test_probe_function_never_prints_content_or_etag(capsys):
    helper = _load_helper()
    verdict = _probe(helper)
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""
    text = json.dumps(verdict)
    assert SECRET_ETAG not in text
    assert "unsupported stream chunk" not in text
    assert "memoryview" not in text
    assert "hash" not in text.lower() and "digest" not in text.lower()
    assert "fingerprint" not in text.lower()


def test_stable_pre_and_post_deployments_allow_verdict():
    helper = _load_helper()
    verdict = _probe(helper)
    assert verdict["ACTIVE_VERSION_MATCH"] == "PASS"
    assert verdict["PR2124_LIVE_MARKERS"] in ("PASS", "INCONCLUSIVE")


def test_post_content_drift_fails_closed_no_pass_claim():
    helper = _load_helper()
    # post read resolves to a different active version
    with pytest.raises(helper.LiveContentError):
        _probe(helper, deployments_post_payload=_deployments(version_id=OTHER))
    # post read lost the single-100% shape (split traffic)
    with pytest.raises(helper.LiveContentError):
        _probe(helper, deployments_post_payload=_deployments(percentage=50))
    # same active but payload shape changed around the fetch => fail closed
    shifted = _deployments()
    shifted["result"]["deployments"].append({"versions": []})
    with pytest.raises(helper.LiveContentError):
        _probe(helper, deployments_post_payload=shifted)
    # pre read drift also fails closed
    with pytest.raises(helper.LiveContentError):
        _probe(helper, deployments_pre_payload=_deployments(version_id=OTHER))


def test_post_content_version_detail_missing_identity_fails_closed():
    helper = _load_helper()
    with pytest.raises(helper.LiveContentError):
        _probe(
            helper,
            version_detail_post_payload={"success": True, "result": {"resources": {}}},
        )
    verdict = _probe(helper, version_detail_post_payload=_detail())
    assert verdict["SCRIPT_IDENTITY_PRESENT"] == "PASS"


def test_pre_read_active_drift_fails_closed():
    helper = _load_helper()
    with pytest.raises(helper.LiveContentError):
        _probe(
            helper,
            deployments_pre_payload=_deployments(version_id=OTHER),
            deployments_post_payload=_deployments(version_id=OTHER),
        )


def test_oversized_and_empty_content_fail_closed():
    helper = _load_helper()
    with pytest.raises(helper.LiveContentError):
        _probe(helper, content_bytes=b"z" * (MAX_BYTES + 1))
    with pytest.raises(helper.LiveContentError):
        _probe(helper, content_bytes=b"")


def test_missing_script_identity_and_structure_fail_closed():
    helper = _load_helper()
    for bad in (
        {"success": True, "result": {"resources": {}}},
        {"success": True, "result": {"resources": {"script": {"etag": ""}}}},
        {"success": True, "result": {}},
        {"success": False, "result": None},
    ):
        with pytest.raises(helper.LiveContentError):
            _probe(helper, version_detail_payload=bad)


def test_ambiguous_traffic_and_bad_uuid_fail_closed():
    helper = _load_helper()
    with pytest.raises(helper.LiveContentError):
        _probe(
            helper,
            deployments_pre_payload=_deployments(percentage=50),
            deployments_post_payload=_deployments(percentage=50),
        )
    with pytest.raises(helper.LiveContentError):
        _probe(helper, expected_active_version="not-a-uuid")


def test_metadata_source_reads_result_metadata_with_exact_closed_enum():
    helper = _load_helper()
    for enum_value in (
        "unknown", "api", "wrangler", "terraform", "dash", "cf_cli",
        "dash_template", "integration", "quick_editor", "playground", "workersci",
    ):
        verdict = _probe(helper, version_detail_payload=_detail(metadata={"source": enum_value}))
        assert verdict["VERSION_METADATA_SOURCE"] == enum_value
    verdict = _probe(helper, version_detail_payload=_detail(metadata={"source": "free-form-value"}))
    assert verdict["VERSION_METADATA_SOURCE"] == "UNKNOWN"
    verdict = _probe(helper, version_detail_payload=_detail())
    assert verdict["VERSION_METADATA_SOURCE"] == "UNKNOWN"
    # legacy wrong paths must NOT be read
    verdict = _probe(helper, version_detail_payload=_detail(sources=["wranglerDeploy"]))
    assert verdict["VERSION_METADATA_SOURCE"] == "UNKNOWN"
    verdict = _probe(helper, version_detail_payload=_detail(source="wrangler"))
    assert verdict["VERSION_METADATA_SOURCE"] == "UNKNOWN"


def test_last_deployed_from_reads_resources_script_path_bounded():
    helper = _load_helper()
    verdict = _probe(helper, version_detail_payload=_detail(last_deployed_from="wrangler-4"))
    assert verdict["SCRIPT_LAST_DEPLOYED_FROM"] == "wrangler-4"
    verdict = _probe(helper, version_detail_payload=_detail(last_deployed_from="x" * 200))
    assert verdict["SCRIPT_LAST_DEPLOYED_FROM"] == "UNKNOWN"
    verdict = _probe(helper, version_detail_payload=_detail(last_deployed_from="has space/bad"))
    assert verdict["SCRIPT_LAST_DEPLOYED_FROM"] == "UNKNOWN"
    verdict = _probe(helper, version_detail_payload=_detail())
    assert verdict["SCRIPT_LAST_DEPLOYED_FROM"] == "UNKNOWN"
    # wrong legacy top-level path must NOT be read
    legacy = _detail()
    legacy["result"]["last_deployed_from"] = "legacy-top"
    verdict = _probe(helper, version_detail_payload=legacy)
    assert verdict["SCRIPT_LAST_DEPLOYED_FROM"] == "UNKNOWN"


def test_author_email_and_author_id_never_emitted(tmp_path):
    helper = _load_helper()
    detail = _detail()
    detail["result"]["author_email"] = SECRET_AUTHOR_EMAIL
    detail["result"]["author_id"] = SECRET_AUTHOR_ID
    f_pre = tmp_path / "pre.json"
    f_post = tmp_path / "post.json"
    f_detail = tmp_path / "detail.json"
    f_content = tmp_path / "content.bin"
    f_pre.write_bytes(json.dumps(_deployments()).encode("utf-8"))
    f_post.write_bytes(json.dumps(_deployments()).encode("utf-8"))
    f_detail.write_bytes(json.dumps(detail).encode("utf-8"))
    f_content.write_bytes(_full_content())
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = helper.main([
            "--deployments-pre", str(f_pre),
            "--deployments-post", str(f_post),
            "--expected-active-version", ACTIVE,
            "--version-detail", str(f_detail),
            "--content", str(f_content),
            "--max-content-bytes", str(MAX_BYTES),
        ])
    assert rc == 0
    combined = out.getvalue() + err.getvalue()
    assert SECRET_AUTHOR_EMAIL not in combined
    assert SECRET_AUTHOR_ID not in combined


def test_cli_failure_is_value_free(tmp_path):
    helper = _load_helper()
    dep_pre = tmp_path / "deployments-pre.json"
    dep_post = tmp_path / "deployments-post.json"
    detail = tmp_path / "detail.json"
    content = tmp_path / "content.bin"
    dep_pre.write_bytes(json.dumps(_deployments()).encode("utf-8"))
    dep_post.write_bytes(json.dumps(_deployments(version_id=OTHER)).encode("utf-8"))
    detail.write_bytes(json.dumps(_detail()).encode("utf-8"))
    content.write_bytes(_full_content())
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = helper.main([
            "--deployments-pre", str(dep_pre),
            "--deployments-post", str(dep_post),
            "--expected-active-version", ACTIVE,
            "--version-detail", str(detail),
            "--content", str(content),
            "--max-content-bytes", str(MAX_BYTES),
        ])
    assert rc == 1
    assert out.getvalue() == ""
    assert "B62_LIVE_CONTENT_PROOF=FAIL" in err.getvalue()
    assert "PRODUCTION_MUTATION=0" in err.getvalue()
    assert SECRET_ETAG not in err.getvalue()
    assert b"unsupported stream chunk".decode() not in err.getvalue()


def test_helper_performs_no_network_io():
    source = HELPER.read_text(encoding="utf-8")
    for token in ("urllib", "http.client", "requests", "socket", "subprocess",
                  "httpx", "curl", "Authorization"):
        assert token not in source, token


def test_helper_reads_no_author_metadata():
    source = HELPER.read_text(encoding="utf-8")
    assert 'get("author' not in source
    assert "author_email=" not in source
    assert "author_id=" not in source


def test_workflow_is_get_only_and_exact_main_guarded():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "EXACT_MAIN=PASS" in workflow
    assert 'test "${GITHUB_REF}" = "refs/heads/main"' in workflow
    assert 'test "$(git rev-parse HEAD)" = "${TARGET_SHA}"' in workflow
    assert 'test "$(git rev-parse origin/main)" = "${TARGET_SHA}"' in workflow
    assert '(.result.deployments | length) >= 1' in workflow
    assert '(.result.deployments | length) == 1' not in workflow
    assert 'if [[ "${active_pre}" != "${EXPECTED_ACTIVE_VERSION}" ]]; then' in workflow
    assert 'if [[ "${active_post}" != "${EXPECTED_ACTIVE_VERSION}" ]]; then' in workflow
    assert "ACTIVE_VERSION_MATCH=FAIL" in workflow
    assert workflow.count("ACTIVE_VERSION_MATCH=FAIL") == 2
    assert "percentage == 100" in workflow
    assert "b62_live_content_marker_probe.py" in workflow
    assert "--deployments-pre" in workflow
    assert "--deployments-post" in workflow
    assert "--version-detail-post" in workflow
    assert "content/v2" in workflow
    assert "RAW_SCRIPT_CONTENT_OUTPUT=0" in workflow
    assert "PRODUCTION_MUTATION=0" in workflow
    assert "permissions:\n  contents: read" in workflow
    for verb in ("-X PATCH", "-X PUT", "-X POST", "-X DELETE", "--data",
                 "wrangler", "rollback", "provider", "/stream"):
        assert verb not in workflow, verb
    assert workflow.count("CLOUDFLARE_API_TOKEN") <= 4


def test_workflow_toctou_ordering():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    readonly = workflow.split("live-content-readonly:", 1)[1]
    pre = readonly.index("b62-live-deployments-pre.json")
    content = readonly.index("content/v2")
    post = readonly.index("b62-live-deployments-post.json")
    assert pre < content < post  # deployments read before AND immediately after content
    detail_post = readonly.index("b62-live-active-detail-post.json")
    assert post < detail_post  # post detail read follows the post deployments guard


def test_workflow_never_prints_or_artifacts_content():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    readonly = workflow.split("live-content-readonly:", 1)[1]
    for token in ("cat ", "jq .", "jq -c", "head -", "tail -", "sha256", "md5",
                  "openssl", "upload-artifact", "FULL_SETTINGS", "/settings"):
        assert token not in readonly, token
    assert "SETTINGS_PAYLOAD_READ=0" in readonly
    assert "rm -f" in readonly  # runner-temp payloads are purged even on failure
    for temp_name in ("b62-live-deployments-pre.json", "b62-live-deployments-post.json",
                      "b62-live-active-detail.json", "b62-live-active-detail-post.json",
                      "b62-live-served-content.bin"):
        assert temp_name in readonly.split("Purge runner-temp payloads", 1)[1], temp_name
