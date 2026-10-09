"""#3790 Slice A — Google subset name projection, network- and execution-free."""
from pathlib import Path

from padiem_control_plane.owner_model_name_parts import (
    PRODUCT_NAME_PREFIX_KO,
    google_owner_name_parts,
)


EXPECTED = {
    "google/gemini-3.1-flash-lite": "Gemini 3.1 Flash Lite",
    "google/gemini-3.5-flash-lite": "Gemini 3.5 Flash Lite",
    "google/gemma-4-26b-a4b-it": "Gemma 4 26B",
    "google/gemma-4-31b-it": "Gemma 4 31B",
}


def test_owner_exact_google_ids_and_name_parts_without_punctuation_guess():
    rows=google_owner_name_parts()
    assert len(rows)==4
    assert {r.model_id:r.individual_model_name for r in rows}==EXPECTED
    assert PRODUCT_NAME_PREFIX_KO=="파디엠플러스"
    assert all(r.product_name_prefix==PRODUCT_NAME_PREFIX_KO for r in rows)
    assert not hasattr(rows[0],"full_display_name")
    assert all(r.owner_selected for r in rows)


def test_registration_evidence_is_not_customer_approval():
    rows=google_owner_name_parts(EXPECTED)
    assert all(r.source_registered_in_b14 for r in rows)
    for row in rows:
        assert row.live_provider_verified is False
        assert row.customer_product_enabled is False
        assert row.customer_selectable is False
        assert row.is_automatic_default is False


def test_missing_registration_fails_closed_and_no_silent_default():
    rows=google_owner_name_parts(())
    assert all(r.source_registered_in_b14 is False for r in rows)
    assert all(r.customer_selectable is False for r in rows)
    assert all(r.is_automatic_default is False for r in rows)


def test_unknown_or_excluded_registration_does_not_add_a_model():
    rows=google_owner_name_parts([
        "kilo/nvidia-nemotron-3-ultra-550b-a55b-free",
        "kilo/poolside-laguna-s-2.1-free",
        "b-ai/qwen3.8-flash",
        "infron/motif/motif-3",
        "experiential/gpt-5.6-luna",
        "poolside/laguna-s-2.1",
        "google/unlisted-model",
    ])
    assert {r.model_id for r in rows}==set(EXPECTED)
    assert all(r.source_registered_in_b14 is False for r in rows)


def test_image_input_is_not_image_generation():
    rows={r.model_id:r for r in google_owner_name_parts(EXPECTED)}
    assert rows["google/gemma-4-31b-it"].image_input_proven_in_prior_fixture is False
    assert all(not r.image_generation_proven for r in rows.values())
    assert all(rows[mid].image_input_proven_in_prior_fixture
               for mid in set(EXPECTED)-{"google/gemma-4-31b-it"})


def test_current_merged_b14_google_source_contains_four_exact_ids():
    repo=Path(__file__).resolve().parents[3]
    source=(repo/"apps/korean-ai-platform/app/pilot/google_provider.py").read_text(encoding="utf-8")
    for mid in EXPECTED:
        assert f'"{mid}"' in source
    assert "https://generativelanguage.googleapis.com/v1beta/openai" in source
