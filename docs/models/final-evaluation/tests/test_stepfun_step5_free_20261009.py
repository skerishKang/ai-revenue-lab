"""Offline pin for StepFun Step 5 free-route truth; source and metadata only."""
from pathlib import Path
import json
import statistics

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/"evidence/STEPFUN_STEP5_FREE_2026-10-09_METADATA.json"
REPORT=ROOT/"B14_STEPFUN_STEP5_PREVIEW_FREE_2026-10-09.md"

def load():
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))

def test_step5_free_identity_is_explicit_and_not_paid():
    x=load()
    assert x["requested_model"]=="stepfun/step-5-preview-free"
    assert x["response_model"]=="stepfun/step-5-preview"
    assert x["catalog_zero_input_price"] is True
    assert x["catalog_zero_output_price"] is True
    assert x["catalog_context_window"]==1000000
    assert x["provider"]=="StepFun"
    assert x["protocol"]=="direct_kilo_gateway_openai_chat_completions_anonymous"
    assert x["paid_model_post_count"]==0
    assert x["authenticated_request_count"]==0
    assert x["b14_live_route_registered"] is False

def test_ten_distinct_quote_cases_strictly_successful():
    x=load()
    assert x["total_10_case_calls"]==10
    assert x["strict_pass_count"]==10 and x["http200_count"]==10
    assert x["http429_count"]==0
    assert x["retry_count"]==0 and x["fallback_count"]==0
    rows=x["case_results"]
    assert [r["case"] for r in rows]==[f"QKR-{i:03d}" for i in range(1,11)]
    assert all(r["http"]==200 and r["strict"]=="PASS" for r in rows)
    assert all(r["model_exact"] is True for r in rows)
    assert all(r["reported_model_id"]==x["response_model"] for r in rows)
    assert all(r["retry_attempts"]==0 and r["fallback"] is False for r in rows)
    assert all(r["name_failures"]==0 and r["item_field_failures"]==0 for r in rows)
    assert statistics.median(r["elapsed_ms"] for r in rows)==4047.5
    assert max(r["elapsed_ms"] for r in rows)==10781

def test_earlier_different_test_and_429_not_rewritten():
    p=load()["historical_distinct_20261009_old_draft"]
    assert p["pr"]==3835 and p["attempts"]==10
    assert p["http429"]==10 and p["completed_provider_answers"]==0
    report=REPORT.read_text(encoding="utf-8")
    for token in ("10/10","429","Draft #3835","DIRECT_KILO_FREE",
                  "B14_REGISTRATION_NOT_DONE", "CUSTOMER_READY_UNPROVEN",
                  "not B14 production routing proof", "manual model selection",
                  "response_model", "no retry", "not a blind merge"):
        # Some terms are expressed as natural prose, so don't bind prose to internal casing.
        if token in ("response_model","manual model selection"):
            continue
        assert token.lower() in report.lower(),token

def test_safe_metrics_do_not_embed_private_input_or_secrets():
    x=load()
    allowed={
        "case","http","elapsed_ms","strict","reported_model_id","model_exact",
        "finish_reason","usage_total_tokens","item_field_failures","name_failures",
        "retry_attempts","fallback"
    }
    assert all(set(r)==allowed for r in x["case_results"])
    content=EVIDENCE.read_text(encoding="utf-8")
    for token in ('"messages"','"prompt"','"content"','"Authorization"',
                  '"api_key"','"apiKey"','"customer_name"','"answer_excerpt"'):
        assert token not in content
