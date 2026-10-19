# -*- coding: utf-8 -*-
"""Generic B66 analyzer/compiler certification test (#3628).

Runs the full generic pipeline — source analysis -> generic compile ->
deterministic render -> certification + bounded mutation robustness — on the
public-safe synthetic second-template fixture, and asserts that the generic
modules carry no document-specific literal.

The fixture layout is deliberately *materially different* from the CGI
reference: landscape page, left-aligned header block, a different item-column
set and different totals wording. Nothing in the generic modules knows any of
that; the slots are derived from the source's own labels.

PyMuPDF is required for PDF rasterization/analysis (the CGI benchmark uses it);
the test skips when it is unavailable rather than failing the lane.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("fitz")

HERE = Path(__file__).resolve().parent
TOOLS = HERE.parent                      # tools/b66_generic
REPO = TOOLS.parent.parent               # repo root
FIXTURES = HERE / "fixtures"
PY = sys.executable


def run(*args):
    r = subprocess.run([PY, *args], capture_output=True, text=True)
    assert r.returncode == 0, f"{args}\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}"
    return r.stdout


def test_generic_pipeline_certifies_synthetic_second_template(tmp_path):
    evidence = tmp_path / "evidence"
    template = tmp_path / "template"
    out = tmp_path / "out"

    run(str(TOOLS / "analyze.py"), "--xlsx", str(FIXTURES / "source.xlsx"),
        "--pdf", str(FIXTURES / "reference.pdf"), "--outdir", str(evidence))
    run(str(TOOLS / "compile_generic.py"), "--evidence", str(evidence),
        "--sheet", "견적서", "--page", "0", "--outdir", str(template))

    tpl = json.loads((template / "quote_template.json").read_text(encoding="utf-8"))
    # the generic compiler derived the expected slot roles from the source labels
    assert set(tpl["mutable_slots"]["camera"]) >= {
        "quote_number", "recipient", "project_name", "issue_date"}
    assert tpl["mutable_slots"]["totals"].keys() >= {"subtotal", "vat", "grand_total"}
    assert tpl["baseline_values"]["quote_number"] == "SYN-2ND-2026-0001"
    assert tpl["baseline_values"]["issue_date_serial"] == 45231
    assert tpl["certification"]["template_specific_literals"] == "none"

    # baseline render must be a byte-identical copy of the reference PDF
    values = tmp_path / "baseline.json"
    values.write_text("{}", encoding="utf-8")
    baseline = out / "baseline.pdf"
    out.mkdir(parents=True, exist_ok=True)
    run(str(TOOLS / "render.py"), "--values", str(values), "--out", str(baseline),
        "--template-dir", str(template))
    assert baseline.read_bytes() == (template / "base_document.pdf").read_bytes()

    # critical fidelity gates, measured separately
    cert = out / "certification.json"
    run(str(TOOLS / "certify.py"), "--template-dir", str(template),
        "--baseline", str(baseline), "--evidence", str(evidence), "--out", str(cert))
    gates = json.loads(cert.read_text(encoding="utf-8"))
    assert gates["SECOND_TEMPLATE_CERTIFICATION"] == "PASS"
    assert all(v == 0 for v in gates["gates"]["RASTER_SIMILARITY"].values())


def test_generic_pipeline_mutation_isolation(tmp_path):
    evidence = tmp_path / "evidence"
    template = tmp_path / "template"
    cases = tmp_path / "cases"
    out = tmp_path / "out"
    cases.mkdir(parents=True)

    run(str(TOOLS / "analyze.py"), "--xlsx", str(FIXTURES / "source.xlsx"),
        "--pdf", str(FIXTURES / "reference.pdf"), "--outdir", str(evidence))
    run(str(TOOLS / "compile_generic.py"), "--evidence", str(evidence),
        "--sheet", "견적서", "--page", "0", "--outdir", str(template))

    payloads = {
        "recipient": {"recipient": "합성변경주식회사"},
        "project": {"project_name": "합성 변경 검증 공사"},
        "date": {"issue_date_serial": 46000},
        "qty": {"items": [{"qty": 2}]},
        "price": {"items": [{"unit_price": 1000}]},
    }
    for name, payload in payloads.items():
        (cases / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False),
                                            encoding="utf-8")
    stdout = run(str(TOOLS / "validate_mutations.py"), "--template-dir", str(template),
                 "--cases", str(cases), "--outdir", str(out), "--dpi", "150")
    assert "FAIL=0" in stdout


def test_generic_modules_have_no_template_literal(tmp_path):
    """No customer/document fact may appear in the generic modules."""
    evidence = tmp_path / "evidence"
    template = tmp_path / "template"
    run(str(TOOLS / "analyze.py"), "--xlsx", str(FIXTURES / "source.xlsx"),
        "--pdf", str(FIXTURES / "reference.pdf"), "--outdir", str(evidence))
    run(str(TOOLS / "compile_generic.py"), "--evidence", str(evidence),
        "--sheet", "견적서", "--page", "0", "--outdir", str(template))
    stdout = run(str(TOOLS / "literal_scan.py"), "--template-dir", str(template),
                 "--evidence", str(evidence), "--modules", str(TOOLS))
    assert '"PASS": true' in stdout
