"""#4117 real PDF-byte local adapter tests, no deployed service or private data."""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
BUNDLE = REPO / "reference/b66-public-standard-templates/cgi/v1/sol61"
SPEC = importlib.util.spec_from_file_location("native_adapter_4117",
                                               HERE / "native_server_adapter.py")
adapter_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter_module)
NativeSolLocalAdapter = adapter_module.NativeSolLocalAdapter
NativeSolRejected = adapter_module.NativeSolRejected


@pytest.fixture(scope="module")
def adapter():
    return NativeSolLocalAdapter(
        bundle=BUNDLE, engine_file=HERE / "sol61_multipage.py")


def fixture_model(adapter, n=1):
    changes = {"items": [
        {"name": f"품목 {i + 1}", "spec": f"규격-{i + 1}", "unit": "EA",
         "qty": i % 5 + 1, "unitPrice": 137000 + i * 9137, "note": ""}
        for i in range(n)
    ]}
    native = adapter.engine.build_slots(changes)
    draft, totals, slots = native["draft"], native["totals"], native["slots"]
    model = {
        "schemaVersion": 1, "derivedBy": "quote-core",
        "template": {"approved": True, "fingerprint": "2" * 64},
        "facts": {
            "sender": {key: draft["sender"].get(key, "") for key in
                       ("company", "rep", "contactPerson", "bizNo", "address", "phone", "email")},
            "recipient": {key: draft["recipient"].get(key, "") for key in
                          ("company", "person", "address", "email")},
            "meta": {"quoteNo": draft["meta"]["quoteNo"],
                     "issueDate": draft["meta"]["issueDate"],
                     "projectName": draft["meta"]["projectName"],
                     "validDays": draft["meta"]["validDays"]},
            "taxRateText": "10%",
        },
        "coreTotals": totals,
        "items": [{
            "index": i, "filler": False,
            "values": {
                "name": slots[f"item{i}Name"], "spec": slots[f"item{i}Spec"],
                "unit": slots[f"item{i}Unit"], "note": slots[f"item{i}Note"],
                "qty": slots[f"item{i}Qty"],
                "unitPrice": "₩" + slots[f"item{i}UnitPrice"],
                "amount": "₩" + slots[f"item{i}Amount"],
            },
        } for i in range(n)],
        "totals": {"subtotalText": "₩" + slots["subtotal"],
                   "vatText": "₩" + slots["vat"],
                   "grandText": "₩" + slots["grand"]},
        "writtenWords": slots["grandWrittenLine"].split("일금 ", 1)[1].split("원정", 1)[0],
        "taxReview": {"required": False},
    }
    return model


def invoke(adapter, model):
    return adapter.render_candidate(model)


def test_4117_real_v1_sol_one_item_exact_frozen_bytes(adapter):
    result = invoke(adapter, fixture_model(adapter))
    pdf = result["pdf"]
    assert pdf[:5] == b"%PDF-"
    assert result["certified"] is False
    assert result["releaseEligible"] is False
    assert "certificateSha256" not in result
    assert result["pageCount"] == len(PdfReader(__import__("io").BytesIO(pdf)).pages) == 1
    assert hashlib.sha256(pdf).hexdigest() == result["pdfSha256"]
    assert result["pdfSha256"] == (
        "5b90ca47ba11b7c9077ab70c49329b4be83b3c82c7106a5ad9c25fdf43b610f6"
    )


@pytest.mark.parametrize("n", [2, 3])
def test_4117_real_v1_two_three_rows_same_bytes_as_certified_engine(adapter, n, tmp_path):
    model = fixture_model(adapter, n)
    output = invoke(adapter, model)
    changes = {"items": [
        {field: row.get(field, "") for field in ("name", "spec", "unit", "note")} | {field: row[field] for field in ("qty", "unitPrice")}
        for row in model["coreTotals"]["effectiveItems"]
    ]}
    baseline = tmp_path / "baseline.pdf"
    adapter.engine.render(baseline, changes)
    assert output["pdf"] == baseline.read_bytes()


@pytest.mark.parametrize("mutation", [
    lambda m: m["coreTotals"].update(grand=m["coreTotals"]["grand"] + 1),
    lambda m: m.update(writtenWords="오류"),
    lambda m: m["totals"].update(grandText="₩999"),
    lambda m: m["items"][0]["values"].update(name="hidden modified name"),
    lambda m: m["facts"]["sender"].update(company="unauthorized company"),
    lambda m: m["facts"].update(taxRateText="0%"),
    lambda m: m["coreTotals"].update(mode="EXEMPT"),
])
def test_4117_no_pdf_for_lying_projection(adapter, mutation):
    model = fixture_model(adapter)
    mutation(model)
    with pytest.raises(NativeSolRejected):
        invoke(adapter, model)


def test_4117_four_item_technical_candidate_but_never_certified(adapter):
    model = fixture_model(adapter, 4)
    result = invoke(adapter, model)
    assert result["certified"] is False
    assert result["pageCount"] == 2
    assert result["pdfSha256"] == (
        "1c96031cece462a8282df1c06e98c2e752612e2c05af353b1ca670cda2aaf248"
    )


def test_4117_historical_private_certificate_cannot_authorize_service(adapter):
    model = fixture_model(adapter)
    with pytest.raises(NativeSolRejected, match="public_release_not_certified"):
        adapter.render_pdf(
            saved_skill_id="b66skill_" + "c" * 32,
            skill_fingerprint="1" * 64, profile_fingerprint="2" * 64,
            render_model=model,
            release={"status": "CERTIFIED", "renderer": "sol61-native",
                     "certificateSha256": adapter.certificate_sha256, "minItems": 1, "maxItems": 3},
        )


def test_4117_public_manifest_cannot_inherit_historical_private_certificate():
    import json
    manifest_path = BUNDLE.parent / "PUBLIC_RELEASE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cert = json.loads((BUNDLE / "certificate.json").read_text(encoding="utf-8"))
    assert manifest["historical_sol_certificate_refers_to_original_private_bundle"] is True
    assert manifest["public_bundle_is_exact_unmodified_source_subset"] is False
    assert manifest["runtime_activation"] is False
    # Public file hash must follow the public release manifest rather than the
    # historical private-package hash inside the source certificate.
    for member in ("engine/quote_template.py", "template/template.json"):
        actual = hashlib.sha256((BUNDLE / member).read_bytes()).hexdigest()
        assert actual == manifest["artifacts"]["sol61/" + member]["sha256"]
        assert actual != cert["packageFiles"][member]
