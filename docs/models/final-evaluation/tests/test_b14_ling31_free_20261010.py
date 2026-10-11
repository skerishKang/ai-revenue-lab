"""Ling 3.1 direct Kilo admission smoke remains correctly ungraded offline."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
EV=ROOT/"evidence/B14_LING31_FLASH_FREE_2026-10-10_METADATA.json"
DOC=ROOT/"B14_LING31_FLASH_FREE_2026-10-10.md"

def test_exact_keyless_free_ling_one_429_stop():
    e=json.loads(EV.read_text(encoding="utf-8"))
    assert e["exact_requested_model"]=="inclusionai/ling-3.1-flash"
    assert e["catalog_http"]==200 and e["catalog_free_prompt_and_completion_price"]
    assert e["catalog_context_window"]==262144
    assert e["route"]=="anonymous_direct_Kilo_Gateway_not_B14"
    assert e["b14_registered"] is False
    assert e["requests"]==e["http429"]==1 and e["responses_http200"]==0
    assert e["accuracy_assessable"] is False
    assert e["retry_count"]==0 and e["automatic_fallback"] is False
    assert e["rate_limit_origin"]=="UNVERIFIED"
    assert e["case"]["case_id"]=="QKR-001"
    assert e["case"]["http_status"]==429
    assert e["case"]["real_model_answer_received"] is False

def test_no_fake_quality_score_and_owner_policies_retained():
    t=DOC.read_text(encoding="utf-8")
    for phrase in ("QUALITY_NOT_ASSESSABLE","UNASSESSABLE","not 0/10",
                   "STOP","no automatic retry","Step 3.7 Flash",
                   "not B14 Worker","NOT RUN","OWNER RETIRED"):
        assert phrase.lower() in t.lower()
    assert "SUPERSEDED" in EV.read_text(encoding="utf-8")

def test_evidence_does_not_embed_text_or_api_secrets():
    content=EV.read_text(encoding="utf-8")
    for sensitive in ('"messages"', '"prompt"', '"content"', '"apiKey"',
                      '"Authorization"','"answer"', '"user_id"', '"customer"'):
        assert sensitive not in content
