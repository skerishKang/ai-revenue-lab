"""Load-bearing render-only authority and fail-closed contract checks."""

from copy import deepcopy
from types import SimpleNamespace
import hashlib
import sys

import pytest

from app.b66_certified_pdf_renderer import B66CertifiedPdfError, _engine, build_changes


def fixture():
    def anchor():
        return {"origin": [20, 30], "cover": [10, 10, 90, 40], "right_x": 90,
                "font": "Synthetic", "size": 10, "color": 0}

    template = {
        "schema": "b66.quote_template.v2",
        "supported_scope": {"max_item_rows": 3, "date_serial_range": [1, 2958465]},
        # These deliberately contradictory sample values must not be used.
        "baseline_values": {"recipient": "FORBIDDEN SAMPLE DEFAULT", "items": []},
        "regions": {"synthetic": [0, 0, 100, 100]},
        "format_rules": {"empty_amount_display": "-", "vat_rate_display": "{rate_percent:.0f}%",
                         "written_total_wrapper": "{words} ({grand_comma})"},
        "mutable_slots": {
            "camera": {
                name: {"spans": [anchor()]} for name in ("quote_number", "recipient", "project_name")
            },
            "item_rows": {str(i): {"anchors": {key: anchor() for key in ("name", "qty", "unit_price", "amount")}}
                          for i in range(1, 4)},
            "totals": {key: anchor() for key in ("subtotal", "vat", "grand_total", "vat_rate_display", "written_total")},
        },
    }
    date_slot = {"spans": [dict(anchor(), kind=part) for part in ("Y", "M", "D")],
                 "group": {"rect": [10, 10, 90, 40]}}
    template["mutable_slots"]["camera"]["issue_date"] = date_slot
    model = {
        "schemaVersion": 1, "derivedBy": "quote-core", "template": {"approved": True},
        "taxReview": {"required": False},
        "facts": {"meta": {"quoteNo": "SYNTHETIC-001", "issueDate": "2026-10-07", "projectName": ""},
                  "recipient": {"company": "Synthetic Recipient"}, "taxRateText": "10%"},
        "coreTotals": {"effectiveItems": [{"name": "Synthetic Item", "qty": 2, "unitPrice": 3}],
                       "amounts": [6], "subtotal": 6, "supply": 6, "vat": 1, "grand": 7,
                       "mode": "EXCLUSIVE", "detailGroups": []},
        "writtenWords": "칠",
    }
    return template, model


def changes(template, base, model):
    return build_changes(template=template, baseline_render_model=base, render_model=model)


def test_noop_uses_resolved_baseline_not_sample_defaults():
    template, model = fixture()
    assert changes(template, model, deepcopy(model)) == []
    mutation = deepcopy(model)
    mutation["facts"]["recipient"]["company"] = "New Recipient"
    changed = changes(template, model, mutation)
    assert [item["slot"] for item in changed] == ["recipient"]
    assert changed[0]["draws"][0]["text"] == "New Recipient"


def test_authoritative_amounts_totals_and_words_are_never_recomputed():
    template, baseline = fixture()
    model = deepcopy(baseline)
    # Keep quantity and price unchanged: these sentinels are intentionally
    # different from any independently calculated amount or VAT formula.
    model["coreTotals"].update(amounts=[71], subtotal=83, supply=83, vat=17, grand=91)
    model["writtenWords"] = "구십일"
    changed = {item["slot"]: item for item in changes(template, baseline, model)}
    assert changed["item_1"]["draws"][0]["text"] == "71"
    assert changed["subtotal"]["draws"][0]["text"] == "83"
    assert changed["vat"]["draws"][0]["text"] == "17"
    assert changed["grand_total"]["draws"][0]["text"] == "91"
    assert changed["written_total"]["draws"][0]["text"] == "구십일 (91)"


@pytest.mark.parametrize("field", ["amounts", "subtotal", "supply", "vat", "grand", "effectiveItems"])
def test_missing_core_values_fail_closed_without_sample_fallback(field):
    template, baseline = fixture()
    incomplete = deepcopy(baseline)
    del incomplete["coreTotals"][field]
    with pytest.raises(B66CertifiedPdfError):
        changes(template, baseline, incomplete)


@pytest.mark.parametrize("value,code", [(-1, "REJECT_NEGATIVE_AMOUNT"),
                                       (True, "REJECT_INVALID_AMOUNT"),
                                       (0.5, "REJECT_INVALID_AMOUNT"),
                                       (float("nan"), "REJECT_INVALID_AMOUNT")])
def test_invalid_canonical_money_rejected(value, code):
    template, baseline = fixture()
    model = deepcopy(baseline)
    model["coreTotals"]["amounts"] = [value]
    with pytest.raises(B66CertifiedPdfError) as error:
        changes(template, baseline, model)
    assert error.value.code == code


@pytest.mark.parametrize("value", ["2026-02-30", "not-a-date", "1800-01-01", None])
def test_resolved_issue_date_is_validated_without_generation(value):
    template, baseline = fixture()
    model = deepcopy(baseline)
    model["facts"]["meta"]["issueDate"] = value
    with pytest.raises(B66CertifiedPdfError):
        changes(template, baseline, model)


def test_removed_row_is_explicitly_cleared_instead_of_retaining_sample():
    template, baseline = fixture()
    baseline["coreTotals"]["effectiveItems"].append({"name": "Second Item", "qty": 1, "unitPrice": 5})
    baseline["coreTotals"]["amounts"].append(5)
    model = deepcopy(baseline)
    model["coreTotals"]["effectiveItems"].pop()
    model["coreTotals"]["amounts"].pop()
    changed = {item["slot"]: item for item in changes(template, baseline, model)}
    assert len(changed["item_2"]["covers"]) == 4
    assert changed["item_2"]["draws"] == []


def test_unresolved_tax_and_unsupported_details_fail_closed():
    template, baseline = fixture()
    model = deepcopy(baseline)
    model["taxReview"]["required"] = True
    with pytest.raises(B66CertifiedPdfError, match="REJECT_UNRESOLVED_TAX"):
        changes(template, baseline, model)
    model = deepcopy(baseline)
    model["coreTotals"]["detailGroups"] = [{"id": "group"}]
    with pytest.raises(B66CertifiedPdfError, match="REJECT_UNSUPPORTED_DETAIL_PAGES"):
        changes(template, baseline, model)


def test_unrecertified_engine_version_fails_closed(monkeypatch):
    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(VersionBind="1.26.4"))
    with pytest.raises(B66CertifiedPdfError, match="PDF_RUNTIME_VERSION_MISMATCH"):
        _engine()


@pytest.mark.parametrize("rate", ["100%", "101%"])
def test_unsupported_resolved_rate_is_rejected(rate):
    template, baseline = fixture()
    model = deepcopy(baseline)
    model["facts"]["taxRateText"] = rate
    with pytest.raises(B66CertifiedPdfError, match="REJECT_INVALID_VAT_RATE"):
        changes(template, baseline, model)


def test_mixed_font_overlay_keeps_distinct_font_resources(monkeypatch):
    # A native mechanism control: full version-pinned Worker certification is
    # executed separately. These synthetic font bytes contain no customer data.
    fitz = pytest.importorskip("fitz")
    import app.b66_certified_pdf_renderer as renderer

    monkeypatch.setattr(renderer, "_engine", lambda: fitz)
    template, baseline = fixture()
    template["page"] = {"count": 1, "width_pt": 100, "height_pt": 100}
    sans, mono = fitz.Font("helv").buffer, fitz.Font("cour").buffer
    fonts = {"fonts/sans.otf": sans, "fonts/mono.otf": mono}
    template["resources"] = {"fonts": {
        "Synthetic": {"file": "fonts/sans.otf", "sha256": hashlib.sha256(sans).hexdigest()},
        "Second": {"file": "fonts/mono.otf", "sha256": hashlib.sha256(mono).hexdigest()},
    }}
    template["mutable_slots"]["totals"]["subtotal"]["font"] = "Second"
    with fitz.open() as document:
        document.new_page(width=100, height=100)
        base_pdf = document.tobytes()
    model = deepcopy(baseline)
    model["coreTotals"].update(amounts=[17], subtotal=29, supply=29)
    output = renderer.render_pdf(template=template, baseline_render_model=baseline,
                                 render_model=model, base_pdf=base_pdf, fonts=fonts)
    with fitz.open(stream=output, filetype="pdf") as document:
        font_names = {font[3] for font in document[0].get_fonts(full=True)}
        assert len(font_names) == 2

def test_changed_slot_removes_source_text_layer_before_overlay(monkeypatch):
    fitz = pytest.importorskip("fitz")
    import app.b66_certified_pdf_renderer as renderer

    monkeypatch.setattr(renderer, "_engine", lambda: fitz)
    template, baseline = fixture()
    template["page"] = {"count": 1, "width_pt": 100, "height_pt": 100}
    font_bytes = fitz.Font("helv").buffer
    template["resources"] = {"fonts": {
        "Synthetic": {
            "file": "fonts/synthetic.otf",
            "sha256": hashlib.sha256(font_bytes).hexdigest(),
        }
    }}
    fonts = {"fonts/synthetic.otf": font_bytes}

    with fitz.open() as document:
        page = document.new_page(width=100, height=100)
        page.insert_text(fitz.Point(20, 30), "Synthetic Recipient", fontsize=10)
        page.insert_text(fitz.Point(5, 80), "UNCHANGED-OUTSIDE", fontsize=8)
        base_pdf = document.tobytes()

    mutation = deepcopy(baseline)
    mutation["facts"]["recipient"]["company"] = "New Recipient"
    output = renderer.render_pdf(
        template=template,
        baseline_render_model=baseline,
        render_model=mutation,
        base_pdf=base_pdf,
        fonts=fonts,
    )
    with fitz.open(stream=output, filetype="pdf") as document:
        text = document[0].get_text("text")
        assert "Synthetic Recipient" not in text
        assert "New Recipient" in text
        assert "UNCHANGED-OUTSIDE" in text
