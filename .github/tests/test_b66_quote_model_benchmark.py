"""No-network tests for B66 quote input interpretation scoring."""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT=Path(__file__).resolve().parents[2]
SCRIPTS=ROOT/".github"/"scripts"
sys.path.insert(0,str(SCRIPTS))
SPEC=importlib.util.spec_from_file_location("b66_quote_model_benchmark",SCRIPTS/"b66_quote_model_benchmark.py")
assert SPEC and SPEC.loader
m=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=m
SPEC.loader.exec_module(m)


def raw_for(case):
    expected=case["expected"]
    return {
        "source":{"kind":"text"},
        "recipient":{"company":expected["recipient_company"]},
        "quote":{"issueDate":expected["issue_date"],"projectName":expected["project_name"]},
        "items":[{"name":x["name"],"qty":x["qty"],"unitPrice":x["unitPrice"]}
                 for x in expected["items"]],
        "tax":{"mode":None},
    }


def test_authority_current_owner_registry_only():
    models=m.approved_models()
    canonical=json.loads((ROOT/"apps/korean-ai-platform/app/pilot/b14_models.json").read_text(encoding="utf8"))
    expected={item["id"] for item in canonical["models"]}
    assert len(set(models))==len(models)
    assert set(models)==expected
    assert not any(name.startswith("kilo/") for name in models)
    assert any(name.startswith("poolside/") for name in models)
    with pytest.raises(ValueError):
        m.select_exact_model("kilo/poolside/laguna-s-2.1:free")
    with pytest.raises(ValueError):
        m.select_exact_model("b14/auto")


def test_same_synthetic_corpus_has_ten_cases_and_multipage_pressure():
    corpus=m.load_corpus()
    assert corpus["provider_calls_authorized"] is False
    assert len(corpus["cases"])==10
    assert tuple(case["id"] for case in corpus["cases"])==m.EXPECTED_IDS
    assert max(len(c["expected"]["items"]) for c in corpus["cases"])>=12
    assert any(c["category"]=="missing_unit_price" for c in corpus["cases"])
    assert any(c["category"]=="correction" for c in corpus["cases"])


@pytest.mark.parametrize("index",range(10))
def test_true_expected_raw_passes_real_B66_normalizer(index):
    case=m.load_corpus()["cases"][index]
    result=m.grade_case(case,raw_for(case))
    assert result["status"]=="PASS",result
    assert result["expected_item_count"]==result["actual_item_count"]


def test_missing_unit_price_is_not_inferred_from_total():
    case=next(c for c in m.load_corpus()["cases"] if c["id"]=="QKR-005")
    correct=raw_for(case)
    assert m.grade_case(case,correct)["status"]=="PASS"
    wrong=json.loads(json.dumps(correct))
    wrong["items"][0]["unitPrice"]=300000
    result=m.grade_case(case,wrong)
    assert result["status"]=="FAIL"
    assert result["item_checks"][0]["unitPrice"] is False


def test_korean_correction_and_undetected_missing_rows_fail():
    corpus=m.load_corpus()
    corrected=next(c for c in corpus["cases"] if c["id"]=="QKR-003")
    wrong=raw_for(corrected)
    wrong["items"][0]["qty"]=10
    assert m.grade_case(corrected,wrong)["status"]=="FAIL"
    many=next(c for c in corpus["cases"] if c["id"]=="QKR-008")
    truncated=raw_for(many)
    truncated["items"]=truncated["items"][:3]
    row=m.grade_case(many,truncated)
    assert row["status"]=="FAIL" and row["expected_item_count"]==12
    assert not row["item_count_correct"]


def test_b66_schema_rejects_malformed_or_missing_source():
    with pytest.raises(ValueError,match="b66_normalizer_rejected"):
        m.normalize_with_b66({"recipient":{"company":"test"}})
    with pytest.raises(ValueError,match="b66_normalizer_rejected"):
        m.normalize_with_b66({"source":{"kind":"unknown"}})


def test_no_historical_sender_leak_in_expected_output():
    for case in m.load_corpus()["cases"]:
        raw=raw_for(case)
        assert "sender" not in raw
        assert "total" not in raw and "grand" not in raw
        assert "PDF" not in json.dumps(raw,ensure_ascii=False)


def test_external_response_envelope_fails_closed_for_fallback_and_identity():
    model=m.approved_models()[0]
    reg=m.load_current_models()[model]
    ans={c["id"]:raw_for(c) for c in m.load_corpus()["cases"]}
    envelope={"model_id":model,"upstream_model":reg["upstream_model"],
        "fallback_used":False,"attempt_count":1,"answers":ans}
    result=m.score_external_responses(model,envelope)
    assert result["cases_passed"]==result["cases_total"]==10
    assert result["model_quality_ranking_eligible"] is False
    assert result["provenance"]=="IMPORTED_RESPONSE_NOT_ATTESTED_LIVE"
    assert result["provider_post_count"]==0
    envelope["fallback_used"]=True
    with pytest.raises(ValueError,match="fallback"):
        m.score_external_responses(model,envelope)
    envelope["fallback_used"]=False
    envelope["model_id"]="not-registered"
    with pytest.raises(ValueError,match="identity_mismatch"):
        m.score_external_responses(model,envelope)


def test_unavailable_and_drift_blocked_by_get_only_preflight():
    model_ids=list(m.approved_models())
    good=[{"id":name} for name in model_ids]
    result=m.live_catalog_preflight(fetch=lambda:json.dumps({"registered_routes":good}).encode())
    assert result["preflight"]=="MATCH"
    assert result["live_post_count"]==0
    drift=[*good,{"id":"retired-test-placeholder"}]
    bad=m.live_catalog_preflight(fetch=lambda:json.dumps({"registered_routes":drift}).encode())
    assert bad["preflight"]=="BLOCKED_REGISTRY_DRIFT"
    assert bad["live_post_count"]==0
    assert bad["unapproved_served_model_ids"]==["retired-test-placeholder"]
    assert m.live_catalog_preflight(fetch=lambda:b"not json")["preflight"]=="UNAVAILABLE"


def test_cli_inert_list_and_exact_prompt_without_real_calls(capsys):
    assert m.main(["--list"])==0
    payload=json.loads(capsys.readouterr().out)
    assert payload["post_count"]==0
    assert set(payload["models"])==set(m.approved_models())
    assert m.main(["--model",m.approved_models()[0],"--prompt","QKR-001"])==0
    prompt=json.loads(capsys.readouterr().out)
    assert "미래설비" in prompt["prompt"]
    assert prompt["live_post_count"]==0
    assert m.main(["--model","b14/auto","--prompt","QKR-001"])==2
    assert "BLOCKED" in capsys.readouterr().out


def test_fixture_cannot_turn_on_live_provider_calls(tmp_path):
    fixture=m.load_corpus()
    fixture["provider_calls_authorized"]=True
    p=tmp_path/"invalid.json"
    p.write_text(json.dumps(fixture,ensure_ascii=False),encoding="utf-8")
    with pytest.raises(ValueError,match="remain_synthetic_offline"):
        m.load_corpus(p)
