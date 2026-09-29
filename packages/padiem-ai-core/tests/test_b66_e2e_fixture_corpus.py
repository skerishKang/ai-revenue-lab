"""#3205 B66 synthetic quotation E2E fixture corpus tests.

Two independent concerns are checked here:

1. The committed corpus is internally consistent — every manifest path exists,
   every byte size and SHA-256 matches, every required case is present, and the
   template-only / variable-content fact split is explicit for every fixture.
2. The corpus is *generated*, not hand-edited: re-running the committed
   generator reproduces the committed bytes (or, for raster fixtures, the
   committed normalized fingerprint), with zero model calls and zero network
   calls.

Fixtures are synthetic and non-sensitive by construction; the tests also prove
the markers are actually inside the generated documents.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import re
import sys
import tempfile
from pathlib import Path

import pytest

CORPUS_DIR = Path(__file__).resolve().parent / "fixtures" / "b66_e2e_corpus"
MANIFEST_PATH = CORPUS_DIR / "manifest.json"
GENERATOR_PATH = CORPUS_DIR / "generate_b66_e2e_fixtures.py"

GENERATOR_DEPENDENCIES = ("reportlab", "pypdf", "pypdfium2", "PIL", "openpyxl")
GENERATOR_READY = all(
    importlib.util.find_spec(name) is not None for name in GENERATOR_DEPENDENCIES
)

# Parsing the committed corpus needs only the document readers. Both workflows
# that run this suite install different dependency sets, so the parse and
# generation checks skip explicitly instead of failing where a reader is
# absent (the manifest-only checks always run).
PARSE_DEPENDENCIES = ("pypdf", "openpyxl")
PARSE_READY = all(
    importlib.util.find_spec(name) is not None for name in PARSE_DEPENDENCIES
)
PARSE_SKIP_REASON = "document reader dependencies are unavailable: " + ", ".join(
    PARSE_DEPENDENCIES
)
GENERATOR_SKIP_REASON = "generator dependencies are unavailable: " + ", ".join(
    GENERATOR_DEPENDENCIES
)

REQUIRED_FIXTURE_IDS = {
    "F01",
    "F02",
    "F03",
    "F04",
    "F05",
    "F06",
    "F07",
    "F08",
    "F09",
    "F10",
    "F11",
    "F12",
    "F13",
}

REQUIRED_MEDIA_TYPES = {
    "application/pdf",
    "image/png",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

SYNTHETIC_MARKER = "SYNTHETIC TEST DATA"

# Deliberately synthetic identifiers: a real business registration number can
# never look like this, and the phone number is the all-zero form.
FAKE_BUSINESS_NUMBER = "000-00-00000"
FAKE_PHONE_NUMBER = "062-000-0000"


def _load_generator():
    assert GENERATOR_READY, GENERATOR_SKIP_REASON
    spec = importlib.util.spec_from_file_location(
        "b66_e2e_fixture_generator", GENERATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # The generator uses ``from __future__ import annotations`` with frozen
    # dataclasses, so it must be registered before execution: dataclasses
    # resolves string annotations through ``sys.modules``.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fixtures(manifest: dict) -> list[dict]:
    return list(manifest["fixtures"])


def _by_id(fixtures: list[dict], fixture_id: str) -> dict:
    for record in fixtures:
        if record["fixture_id"] == fixture_id:
            return record
    raise AssertionError(f"fixture {fixture_id} is missing from the manifest")


def test_manifest_declares_the_corpus_contract(manifest: dict) -> None:
    assert manifest["issue"] == "#3205"
    assert manifest["parent_issue"] == "#3186"
    assert manifest["synthetic"] is True
    assert manifest["non_sensitive"] is True
    assert manifest["model_calls"] == 0
    assert manifest["network_calls"] == 0
    assert manifest["quote_core_calculation_authority"] is True
    assert manifest["fixture_totals_are_expected_source_facts_only"] is True
    assert manifest["frozen_at"] == "before-any-model-call"
    assert set(manifest["determinism_contract"]) == {"byte_identical", "normalized"}


def test_all_manifest_paths_exist_and_are_non_empty(
    manifest: dict, fixtures: list[dict]
) -> None:
    assert len(fixtures) == len(REQUIRED_FIXTURE_IDS)
    for record in fixtures:
        path = CORPUS_DIR / record["relative_path"]
        assert path.is_file(), f"missing fixture file {record['relative_path']}"
        assert path.stat().st_size > 0
        assert record["byte_size"] > 0
        # No fixture may be resolved outside the corpus directory.
        assert path.resolve().parent == CORPUS_DIR.resolve()


def test_fixture_ids_and_paths_are_unique(fixtures: list[dict]) -> None:
    ids = [record["fixture_id"] for record in fixtures]
    paths = [record["relative_path"] for record in fixtures]
    assert len(ids) == len(set(ids))
    assert len(paths) == len(set(paths))
    assert set(ids) == REQUIRED_FIXTURE_IDS


def test_fixture_byte_size_and_sha256_match_the_committed_files(
    fixtures: list[dict],
) -> None:
    for record in fixtures:
        payload = (CORPUS_DIR / record["relative_path"]).read_bytes()
        assert len(payload) == record["byte_size"], record["relative_path"]
        assert hashlib.sha256(payload).hexdigest() == record["sha256"], record[
            "relative_path"
        ]


def test_every_fixture_declares_synthetic_true(fixtures: list[dict]) -> None:
    for record in fixtures:
        assert record["synthetic"] is True, record["fixture_id"]


def test_required_media_types_are_present(fixtures: list[dict]) -> None:
    present = {record["media_type"] for record in fixtures}
    assert REQUIRED_MEDIA_TYPES.issubset(present)


def test_required_case_coverage_is_present(fixtures: list[dict]) -> None:
    vat_modes = {record["vat_mode"] for record in fixtures}
    assert {"separate", "inclusive", "exempt"}.issubset(vat_modes)

    assert any(record.get("column_order_variant") for record in fixtures)
    assert _by_id(fixtures, "F05")["column_order"] != _by_id(fixtures, "F01")[
        "column_order"
    ]

    assert _by_id(fixtures, "F02")["media_type"] == "image/png"
    assert _by_id(fixtures, "F11")["media_type"] == "image/png"
    assert _by_id(fixtures, "F13")["media_type"] == "image/png"

    assert _by_id(fixtures, "F12")["page_count_or_sheet_count"] >= 2
    assert _by_id(fixtures, "F09")["unknown_stays_unknown"] is True
    assert _by_id(fixtures, "F10")["fixed_terms"]
    assert _by_id(fixtures, "F10")["template_fixed_terms"]

    for record in fixtures:
        assert record["source_kind"] in {"native_document", "raster_image"}


def test_template_and_variable_facts_are_both_explicit(fixtures: list[dict]) -> None:
    for record in fixtures:
        assert isinstance(record["template_only_facts"], list)
        assert isinstance(record["variable_content_facts"], list)
        if record["fixture_id"] == "F11":
            # The logo card carries template facts only: no per-quote content.
            assert record["variable_content_facts"] == []
        else:
            assert record["template_only_facts"], record["fixture_id"]
            assert record["variable_content_facts"], record["fixture_id"]
        # A fact may not silently be claimed as both template and variable.
        assert not set(record["template_only_facts"]) & set(
            record["variable_content_facts"]
        )


def test_fixture_totals_are_self_consistent_but_not_an_authority(
    fixtures: list[dict],
) -> None:
    for record in fixtures:
        facts = record["expected_business_facts"]
        if record["fixture_id"] in {"F11"}:
            continue
        amounts = [
            int(item["amount"].replace(",", "")) for item in facts["items"]
        ]
        supply = int(facts["supply_amount"].replace(",", ""))
        assert sum(amounts) == supply, record["fixture_id"]
        if record["vat_mode"] == "separate":
            vat = int(facts["vat_amount"].replace(",", ""))
            total = int(facts["total_amount"].replace(",", ""))
            assert supply + vat == total, record["fixture_id"]
        if record["vat_mode"] in {"inclusive", "exempt"}:
            assert int(facts["total_amount"].replace(",", "")) == supply


def test_missing_field_case_keeps_absent_facts_unknown(fixtures: list[dict]) -> None:
    facts = _by_id(fixtures, "F09")["expected_business_facts"]
    assert facts["quote_number"] is None
    assert facts["quote_date"] is None
    assert facts["vat_wording"] is None
    assert facts["memo"] is None
    assert set(facts["intentionally_missing_facts"]) == {
        "quote_number",
        "quote_date",
        "vat_wording",
        "memo",
    }


@pytest.mark.skipif(not PARSE_READY, reason=PARSE_SKIP_REASON)
def test_pdf_fixtures_carry_a_native_text_layer(fixtures: list[dict]) -> None:
    document_normalization = importlib.import_module(
        "padiem_ai_core.document_normalization"
    )
    for record in fixtures:
        if record["media_type"] != "application/pdf":
            continue
        payload = (CORPUS_DIR / record["relative_path"]).read_bytes()
        inspection = document_normalization.inspect_pdf(
            name=record["relative_path"],
            media_type="application/pdf",
            payload=payload,
        )
        assert inspection.native_text_available is True, record["fixture_id"]
        assert inspection.page_count == record["page_count_or_sheet_count"]
        text = "\n".join(page.text for page in inspection.pages)
        assert SYNTHETIC_MARKER in text, record["fixture_id"]
        facts = record["expected_business_facts"]
        if facts["quote_number"]:
            assert facts["quote_number"] in text
        if facts["supply_amount"]:
            assert facts["supply_amount"] in text
        # Absent facts must really be absent from the rendered document.
        for missing in facts["intentionally_missing_facts"]:
            if missing == "quote_number":
                assert re.search(r"Q-\d{4}-\d{4}", text) is None


@pytest.mark.skipif(not PARSE_READY, reason=PARSE_SKIP_REASON)
def test_docx_and_xlsx_parse_through_the_core_authority(
    fixtures: list[dict],
) -> None:
    document_normalization = importlib.import_module(
        "padiem_ai_core.document_normalization"
    )
    docx = _by_id(fixtures, "F03")
    docx_text = document_normalization.extract_docx_text(
        (CORPUS_DIR / docx["relative_path"]).read_bytes()
    )
    assert docx["expected_business_facts"]["quote_number"] in docx_text
    assert "실사용 금지" in docx_text

    xlsx = _by_id(fixtures, "F04")
    xlsx_text = document_normalization._extract_xlsx_text(
        (CORPUS_DIR / xlsx["relative_path"]).read_bytes()
    )
    assert xlsx["expected_business_facts"]["quote_number"] in xlsx_text


def test_synthetic_identifiers_only(fixtures: list[dict]) -> None:
    for record in fixtures:
        facts = record["expected_business_facts"]
        sender = facts.get("sender")
        if sender is not None:
            assert sender.upper() == "TEST SUPPLIER CO" or sender == "주식회사 테스트상사"
        assert FAKE_BUSINESS_NUMBER not in json.dumps(facts)
        assert FAKE_PHONE_NUMBER not in json.dumps(facts)
        for item in facts.get("items", []):
            assert not re.search(r"\d{6}-\d{2}-\d{5}", item["description"])


def test_generator_source_declares_no_network_or_model_dependency() -> None:
    source = GENERATOR_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "import requests",
        "import urllib",
        "import socket",
        "import httpx",
        "urlopen",
        "api.kilo.ai",
        "openrouter.ai",
    ):
        assert forbidden not in source, f"generator references {forbidden}"


@pytest.mark.skipif(not GENERATOR_READY, reason=GENERATOR_SKIP_REASON)
def test_generation_is_deterministic(fixtures: list[dict]) -> None:
    module = _load_generator()
    with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
        first_manifest = module.generate(Path(first))
        second_manifest = module.generate(Path(second))

        # The generator itself must be stable between two runs in one process.
        for record in fixtures:
            name = record["relative_path"]
            first_bytes = (Path(first) / name).read_bytes()
            second_bytes = (Path(second) / name).read_bytes()
            assert first_bytes == second_bytes, name

            if record["determinism"] == "byte_identical":
                committed = (CORPUS_DIR / name).read_bytes()
                assert first_bytes == committed, (
                    f"{name} is declared byte_identical but the committed file "
                    "does not reproduce"
                )
            else:
                assert record["determinism"] == "normalized"
                assert (
                    module.normalized_image_fingerprint(first_bytes)
                    == record["normalized_fingerprint"]
                ), name

        # The manifests must agree with each other and with the committed one.
        committed_manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        assert first_manifest == second_manifest == committed_manifest
