"""Safe, bounded direct free Gateway benchmark evidence; no network required."""
import json
import statistics
from pathlib import Path

HERE=Path(__file__).resolve().parents[1]
EVIDENCE=HERE/"evidence/B14_DOTS3_NOTE_FREE_2026-10-10_METADATA.json"
REPORT=HERE/"B14_DOTS3_NOTE_FREE_2026-10-10.md"

def test_free_id_catalog_not_an_inferred_b14_or_paid_model():
    d=json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert d["requested_model"]=="dots-studio/dots-3-note-preview:free"
    assert d["zero_prompt_price"] and d["zero_completion_price"]
    assert d["context_length"]==512000 and d["access"]=="anonymous_kilo_gateway_direct"
    assert d["b14_registered"] is False and d["customer_ready"] is False
    assert d["retry_count"]==0 and d["fallback_count"]==0

def test_exact_ten_case_data_is_consistent():
    d=json.loads(EVIDENCE.read_text(encoding="utf-8"))
    r=d["case_results"]
    assert d["cases_attempted"]==10 and len(r)==10
    assert [x["case"] for x in r]==[f"QKR-{i:03d}" for i in range(1,11)]
    assert d["http200"]==sum(x["http"]==200 for x in r)
    assert d["strict_pass"]==sum(x["strict"]=="PASS" for x in r)
    assert d["http429"]==sum(x["http"]==429 for x in r)
    assert all(x["fallback"] is False and x["retry_attempts"]==0 for x in r)
    assert all(x["model_exact"] is True for x in r if x["http"]==200)
    lat=[x["elapsed_ms"] for x in r if x["http"]==200]
    assert d["median_completed_ms"]==statistics.median(lat)
    q7=next(x for x in r if x["case"]=="QKR-007")
    assert q7["http"]==200 and q7["strict"]=="UNAVAILABLE"
    assert q7["reply_present"] is False
    assert q7["finish_reason"]=="length"
    assert q7["usage_total_tokens"]==3862

def test_report_is_explicit_about_routing_and_owner_retired_step37():
    s=REPORT.read_text(encoding="utf-8")
    for snippet in ("NOT_B14_REGISTERED","NOT_CUSTOMER_READY","StepFun","3.7 Flash",
                    "no retries/fallback","Production B14 Worker","same synthetic QKR"):
        assert snippet.lower() in s.lower()

def test_no_model_responses_or_secrets_are_committed():
    d=json.loads(EVIDENCE.read_text(encoding="utf-8"))
    s=json.dumps(d,ensure_ascii=False)
    for fragment in ('"messages"', '"content"', '"apiKey"', '"Authorization"', '"customer_name"', '"answer"'):
        assert fragment not in s
