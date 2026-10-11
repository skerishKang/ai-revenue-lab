"""Immutable, synthetic, raw-response-free B14 same-case model comparison guard."""
import json
import statistics
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REPORT=ROOT/"B14_SAME_CASE_MODEL_COMPARISON_2026-10-09.md"
EVIDENCE=ROOT/"evidence/B14_MODEL_COMPARISON_2026-10-09_METADATA.json"

def load():
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))

def test_dataset_fixed_uniform_conditions_and_model_choice():
    e=load()
    assert e["round"]=="20261009-B14-MODELCOMPARE-V2"
    assert e["prompt_separator"]=="actual_newline"
    assert e["temperature"]==0
    assert e["max_tokens"]==3500
    assert e["requests_per_case"]==1 and e["retry_count"]==0
    assert e["fallback_used"] is False
    assert [m["id"] for m in e["models"]]==[
        "inception/mercury-2.5",
        "google/gemini-3.5-flash-lite",
        "sensenova/sensenova-6.8-flash-lite"]
    for m in e["models"]:
        assert [r["case"] for r in m["cases"]]==[f"QKR-{i:03d}" for i in range(1,11)]
        for r in m["cases"]:
            assert r["http"] in (200,504)
            if r["http"]==200:
                assert r["route_ok"] and r["attempt_count"]==1 and r["fallback_used"] is False
            assert not (r["http"]!=200 and r["strict"]=="PASS")

def test_aggregates_derived_from_exact_evidence():
    e=load()
    expected=[(10,9,0,3874),(7,7,3,6547),(7,7,3,6766)]
    for m, (expected_http,expected_pass,expected_504,expected_median) in zip(e["models"],expected):
        rows=m["cases"]
        times=[r["latency_ms"] for r in rows if r["http"]==200]
        assert (len(times),sum(r["strict"]=="PASS" for r in rows),
                sum(r["http"]==504 for r in rows),int(statistics.median(times)))==(
                    expected_http,expected_pass,expected_504,expected_median)
    qkr8=e["models"][0]["cases"][7]
    assert qkr8["case"]=="QKR-008" and qkr8["http"]==200
    assert qkr8["strict"]=="FAIL"
    assert qkr8["name_failures"]==0
    assert qkr8["item_field_failures"]==9
    assert qkr8["item_count_correct"] is True

def test_atria_exact_effort_bounded_direct_provider_evidence():
    rows=load()["atria_direct_reasoning"]
    assert [(r["mode"],r["http"],r["done"],r["strict"]) for r in rows]==[
        ("low",200,True,"PASS"),("medium",200,True,"PASS"),("high",200,True,"PASS")]
    assert [r["elapsed_ms"] for r in rows]==[22172,24313,43922]
    assert [r["first_delta_ms"] for r in rows]==[17328,19969,37703]

def test_document_distinguishes_historical_and_live_and_no_auto_model_change():
    text=REPORT.read_text(encoding="utf-8")
    for marker in ("9/10", "7/10", "HTTP504", "DIRECT PROVIDER ONLY",
                   "no production deployment", "no fallback", "8/10",
                   "10/10", "n=10", "Agnes", "Source", "Customer"):
        assert marker.lower() in text.lower()
    assert "*not* confirmation that live B14 generic gateway forwards" in text
    assert "User-facing model choice remains manual" in text

def test_no_prompt_or_secrets_stored_with_metadata():
    content=EVIDENCE.read_text(encoding="utf-8")
    for fragment in ('"answer":', '"messages":','"Authorization":','"apiKey":',
                     '"prompt_text":','"account_id":','"request_id":'):
        assert fragment not in content
