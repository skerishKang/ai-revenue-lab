"""#3936 Hark benchmark E2E: independent, fail-closed evidence and XLSX fidelity.

This verifier never mutates a workbook, dispatches a model, grants access or
promotes a mocked local browser observation to authenticated Production E2E.
Use only synthetic fixture bytes or owner-authorized private evidence outside git.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
SCENES = (
    "01_empty_chat",
    "02_natural_language_request",
    "03_accepted_execution",
    "04_canonical_phase_transition",
    "05_intermediate_progress",
    "06_real_pdf_artifact_card",
    "07_owner_scoped_pdf_preview",
    "08_authorized_download",
)
EXPECTED_VALUES = {
    "original_supply": 88000000,
    "updated_supply": 99200000,
    "updated_vat": 9920000,
    "updated_total": 109120000,
}


class Hark3936EvidenceError(ValueError):
    pass


def _sheet(data: bytes) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    """Read-only OOXML inspection; fail closed on macros/external links/zip bombs."""
    if type(data) is not bytes or not 100 <= len(data) <= 12 * 1024 * 1024:
        raise Hark3936EvidenceError("XLSX_SIZE_UNTRUSTED")
    try:
        import io
        with ZipFile(io.BytesIO(data), "r") as archive:
            names = archive.namelist()
            if (len(names) != len(set(names)) or len(names) > 120
                    or any("/../" in name or name.startswith("/") or "\\" in name for name in names)
                    or any("externalLink" in name or "vbaProject" in name for name in names)
                    or sum(item.file_size for item in archive.infolist()) > 32 * 1024 * 1024):
                raise Hark3936EvidenceError("XLSX_UNTRUSTED_PACKAGE")
            if "xl/worksheets/sheet1.xml" not in names:
                raise Hark3936EvidenceError("XLSX_SHEET_MISSING")
            if archive.testzip() is not None:
                raise Hark3936EvidenceError("XLSX_CRC_INVALID")
            data_xml = archive.read("xl/worksheets/sheet1.xml")
    except (BadZipFile, KeyError, OSError, ValueError) as exc:
        raise Hark3936EvidenceError("XLSX_BAD_PACKAGE") from exc
    try:
        xml = ET.fromstring(data_xml)
    except ET.ParseError as exc:
        raise Hark3936EvidenceError("XLSX_BAD_XML") from exc
    cells = {}
    for cell in xml.iter(MAIN + "c"):
        address = cell.get("r")
        if not address or address in cells:
            raise Hark3936EvidenceError("XLSX_DUPLICATE_CELL")
        value = cell.find(MAIN + "v")
        formula = cell.find(MAIN + "f")
        cells[address] = {"value": value.text if value is not None else None,
                          "formula": formula.text if formula is not None else None,
                          "style": cell.get("s")}
    merges = tuple(sorted(item.get("ref", "") for item in xml.iter(MAIN + "mergeCell")))
    return cells, merges


def _decimal(cells: dict, location: str) -> Decimal:
    raw = cells.get(location, {}).get("value")
    if not isinstance(raw, str):
        raise Hark3936EvidenceError("XLSX_MISSING_CACHED_VALUE")
    try:
        amount = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise Hark3936EvidenceError("XLSX_INVALID_AMOUNT") from exc
    if not amount.is_finite():
        raise Hark3936EvidenceError("XLSX_NONFINITE_AMOUNT")
    return amount


def verify_synthetic_quote_pair(
    *, original: bytes, updated: bytes, recorded_original_sha256: str
) -> dict[str, object]:
    """Check genuine OOXML value, formula, cache and formatting fidelity.

    This only proves OFFLINE TEST DATA; it is not an authorized real user's
    workbook edit, Excel renderer, printable PDF or Drive receipt.
    """
    original_sha = hashlib.sha256(original).hexdigest()
    updated_sha = hashlib.sha256(updated).hexdigest()
    if (not isinstance(recorded_original_sha256, str)
            or recorded_original_sha256 != original_sha
            or original_sha == updated_sha):
        raise Hark3936EvidenceError("SOURCE_INTEGRITY_MISSING_OR_UNCHANGED")
    a, a_merges = _sheet(original)
    b, b_merges = _sheet(updated)
    if (a_merges != b_merges or "A1:D1" not in b_merges):
        raise Hark3936EvidenceError("MERGED_RANGE_CHANGED")
    if (_decimal(a, "B4") != EXPECTED_VALUES["original_supply"]
            or _decimal(b, "B4") != EXPECTED_VALUES["updated_supply"]
            or _decimal(b, "B5") != Decimal("0.1")):
        raise Hark3936EvidenceError("QUOTE_INPUT_VALUES_MISMATCH")
    if (a.get("B6", {}).get("formula") != b.get("B6", {}).get("formula")
            or b.get("B6", {}).get("formula") != "B4*B5"
            or a.get("B7", {}).get("formula") != b.get("B7", {}).get("formula")
            or b.get("B7", {}).get("formula") != "SUM(B4,B6)"):
        raise Hark3936EvidenceError("FORMULA_FIDELITY_FAILED")
    if (_decimal(b, "B6") != EXPECTED_VALUES["updated_vat"]
            or _decimal(b, "B7") != EXPECTED_VALUES["updated_total"]):
        raise Hark3936EvidenceError("CALCULATED_VALUES_FAILED")
    if set(a) != set(b):
        raise Hark3936EvidenceError("UNREQUESTED_CELL_ADDED_OR_REMOVED")
    for key in a:
        if a[key]["style"] != b[key]["style"]:
            raise Hark3936EvidenceError("STYLE_FIDELITY_FAILED")
        if key not in ("B4", "B6", "B7") and a[key] != b[key]:
            raise Hark3936EvidenceError("UNREQUESTED_CELL_CHANGED")
    return {
        "test_fixture_pair": "PASS",
        "source_integrity_preserved": "PASS",
        "formula_and_style_fidelity": "PASS",
        "synthetic_supply_amount": EXPECTED_VALUES["updated_supply"],
        "synthetic_vat": EXPECTED_VALUES["updated_vat"],
        "synthetic_total": EXPECTED_VALUES["updated_total"],
        "original_sha256": original_sha,
        "updated_sha256": updated_sha,
        "real_user_execution": False,
        "real_pdf_export": False,
        "production_owner_authority": False,
    }


def acceptance_matrix(
    *,
    supported_component_scenes: set[str] | frozenset[str] = frozenset(),
    private_reference_scenes: set[str] | frozenset[str] = frozenset(),
    synthetic_fixture_checked: bool = False,
    production_e2e_observed: bool = False,
) -> dict[str, Any]:
    """Truth-preserving status projection. No caller-provided flag mints live PASS."""
    if not (set(supported_component_scenes) <= set(SCENES)
            and set(private_reference_scenes) <= set(SCENES)):
        raise Hark3936EvidenceError("UNRECOGNIZED_SCENE_ID")
    stages = []
    for scene in SCENES:
        component = scene in supported_component_scenes
        baseline = scene in private_reference_scenes
        stages.append({
            "scene": scene,
            "reference_private": baseline,
            "source_contract_tested": component,
            # A manually asserted boolean does NOT authenticate a real run.
            "real_authenticated_user_e2e": "NOT_INDEPENDENTLY_VERIFIED",
        })
    blockers = [
        "PRODUCTION_OWNER_SIGNED_IN_PROVIDER_GOLDEN_PATH_UNVERIFIED",
        "REAL_SELECTED_MODEL_TOOL_AND_EVENT_TRACE_UNVERIFIED",
        "ACTUAL_XLSX_COPY_ON_WRITE_AND_PDF_FIDELITY_UNVERIFIED",
        "OWNER_AUTHORIZED_PREVIEW_DOWNLOAD_AND_FOLLOWUP_UNVERIFIED",
        "REAL_DESKTOP_MOBILE_8_SCENE_CAPTURE_UNVERIFIED",
    ]
    if not synthetic_fixture_checked:
        blockers.append("SYNTHETIC_XLSX_INTEGRITY_TEST_PENDING")
    if len(private_reference_scenes) != len(SCENES):
        blockers.append("PRIVATE_BENCHMARK_SCENE_SET_INCOMPLETE")
    return {
        "issue": 3936,
        "contract": "hark-8-scene-evidence.v1",
        "scenes": stages,
        "local_component_evidence_count": sum(s["source_contract_tested"] for s in stages),
        "baseline_scenes_count": sum(s["reference_private"] for s in stages),
        "synthetic_fixture_checked": bool(synthetic_fixture_checked),
        "production_claim_requested": bool(production_e2e_observed),
        "disposition": "BLOCKED_REAL_E2E",
        "hark_behavioral_parity": "NOT_EVIDENCED",
        "production_live": "NOT_VERIFIED",
        "blockers": blockers,
        "credentials_or_private_artifacts_output": 0,
    }
