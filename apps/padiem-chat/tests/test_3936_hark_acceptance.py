"""#3936: Hark 8-scene honest acceptance, no mock-to-production promotion."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.hark_3936_acceptance import (
    EXPECTED_VALUES, Hark3936EvidenceError, SCENES,
    acceptance_matrix, verify_synthetic_quote_pair,
)

ROOT = Path(__file__).resolve().parents[1]
TEST_DIR = ROOT / "tests"
STATIC = ROOT / "static"


def test_all_eight_benchmark_scenes_are_explicit_and_unique():
    assert len(SCENES) == len(set(SCENES)) == 8
    assert [v[:2] for v in SCENES] == [f"{n:02d}" for n in range(1, 9)]


def test_real_component_test_files_exist_and_not_marked_full_qa():
    files = [
        "test_3382_claw_general_answer_dom.py",
        "test_3930_claw_run_event_projection.py",
        "test_3932_artifact_owner_preview_boundary.py",
        "test_3933_bounded_document_edit_intent.py",
        "test_3934_owner_lineage_display.py",
        "test_3935_claw_general_recovery_truth.py",
        "test_b54_claw_general_rate_limit_recovery_3566.py",
        "test_b54_claw_run_history_ui.py",
    ]
    for name in files:
        assert (TEST_DIR / name).is_file(), name
    assert (STATIC / "app.js").is_file()
    assert (STATIC / "claw-recovery-truth.js").is_file()


def test_offline_sources_cannot_forge_product_completion():
    matrix = acceptance_matrix(
        supported_component_scenes=set(SCENES),
        private_reference_scenes=set(SCENES),
        synthetic_fixture_checked=True,
        production_e2e_observed=True,
    )
    assert matrix["local_component_evidence_count"] == 8
    assert matrix["disposition"] == "BLOCKED_REAL_E2E"
    assert matrix["hark_behavioral_parity"] == "NOT_EVIDENCED"
    assert all(item["real_authenticated_user_e2e"] == "NOT_INDEPENDENTLY_VERIFIED"
               for item in matrix["scenes"])
    assert len(matrix["blockers"]) == 5
    assert matrix["credentials_or_private_artifacts_output"] == 0


def test_missing_reference_and_fixture_have_distinct_blockers():
    matrix = acceptance_matrix(supported_component_scenes={SCENES[0]})
    assert matrix["baseline_scenes_count"] == 0
    assert matrix["local_component_evidence_count"] == 1
    assert "PRIVATE_BENCHMARK_SCENE_SET_INCOMPLETE" in matrix["blockers"]
    assert "SYNTHETIC_XLSX_INTEGRITY_TEST_PENDING" in matrix["blockers"]


def test_unknown_scene_fails_closed():
    with pytest.raises(Hark3936EvidenceError, match="UNRECOGNIZED_SCENE_ID"):
        acceptance_matrix(private_reference_scenes={"hark_fake_09"})


def test_approved_synthetic_targets_are_exact_and_formula_driven():
    assert EXPECTED_VALUES == {
        "original_supply": 88000000,
        "updated_supply": 99200000,
        "updated_vat": 9920000,
        "updated_total": 109120000,
    }
    assert EXPECTED_VALUES["updated_supply"] // 10 == EXPECTED_VALUES["updated_vat"]
    assert EXPECTED_VALUES["updated_supply"] + EXPECTED_VALUES["updated_vat"] == EXPECTED_VALUES["updated_total"]


def test_missing_or_non_zip_xlsx_cannot_claim_fidelity():
    src = b"not a real workbook" * 20
    modified = b"also not a real workbook" * 20
    with pytest.raises(Hark3936EvidenceError, match="XLSX_BAD_PACKAGE"):
        verify_synthetic_quote_pair(original=src, updated=modified,
                                    recorded_original_sha256=hashlib.sha256(src).hexdigest())
    with pytest.raises(Hark3936EvidenceError, match="SOURCE_INTEGRITY"):
        verify_synthetic_quote_pair(original=src, updated=modified,
                                    recorded_original_sha256="0" * 64)


def test_source_and_working_bytes_cannot_be_identical():
    src = b"content with enough bytes" * 20
    with pytest.raises(Hark3936EvidenceError, match="SOURCE_INTEGRITY"):
        verify_synthetic_quote_pair(original=src, updated=src,
                                    recorded_original_sha256=hashlib.sha256(src).hexdigest())


def test_acceptance_code_has_no_live_provider_mutations_or_private_paths():
    source = (ROOT / "app" / "hark_3936_acceptance.py").read_text(encoding="utf-8")
    for forbidden in ("E:\\\\PADIEM_CLAW_HARK", "cloudflare_api_token", "requests.post(",
                      "subprocess.run(", "client.post(", "put_object(", "gh api ", "wrangler deploy"):
        assert forbidden not in source
    assert "BLOCKED_REAL_E2E" in source
    assert "NOT_INDEPENDENTLY_VERIFIED" in source


def test_source_only_cli_exits_nonzero_even_with_all_eight_claimed_component_scenes():
    import subprocess
    import sys
    import json

    cli = ROOT / "scripts" / "hark_3936_acceptance.py"
    result = subprocess.run(
        [sys.executable, str(cli), "--tested-scenes", *SCENES],
        capture_output=True, text=True, encoding="utf-8", timeout=15, check=False,
    )
    assert result.returncode == 3
    report = json.loads(result.stdout)
    assert report["local_component_evidence_count"] == 8
    assert report["disposition"] == "BLOCKED_REAL_E2E"
    assert "HARK_3936_STATUS=BLOCKED_REAL_E2E" in result.stderr
