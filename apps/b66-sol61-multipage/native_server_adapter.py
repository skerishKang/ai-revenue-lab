"""Local/hosted-Python #4117 adapter for the immutable Sol 6.1 engine.

This is an offline execution candidate, NOT wired into the Cloudflare Worker.
It requires exact licensed Windows font files and independently injected release
authority. V2 remains blocked until a separately reviewed certificate exists.
"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from pypdf import PdfReader

_SHA = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_FILES = (
    "engine/quote_template.py", "engine/font_support.py", "engine/slots.cjs",
    "quote-core.js", "template/program.zlib", "template/resources.pdf",
    "template/template.json",
)


class NativeSolRejected(ValueError):
    """Fail-closed client input, source, release, or runtime mismatch."""


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise NativeSolRejected(reason)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _money_display(value: Any, expected: str) -> bool:
    """Require the exact KRW display, without accepting negative signs."""
    return isinstance(value, str) and value == "₩" + expected


def _qty_display(value: Any, expected: str) -> bool:
    """Only locale grouping commas are permitted in a quantity string."""
    return (isinstance(value, str) and
            re.fullmatch(r"[0-9][0-9,]*(?:\.[0-9]{1,2})?", value) is not None and
            value.replace(",", "") == expected)


class NativeSolLocalAdapter:
    def __init__(self, *, bundle: Path, engine_file: Path, node: str = "node"):
        self.bundle = Path(bundle).resolve()
        self.engine_file = Path(engine_file).resolve()
        self.certificate_file = self.bundle / "certificate.json"
        _require(self.certificate_file.is_file() and self.engine_file.is_file(),
                 "native_sol_source_missing")
        cert_bytes = self.certificate_file.read_bytes()
        self.certificate_sha256 = _sha(cert_bytes)
        cert = json.loads(cert_bytes)
        _require(cert.get("status") == "CERTIFIED" and
                 cert.get("supportedItemCount", {}).get("maximum") == 3,
                 "native_sol_v1_certificate_invalid")
        # This is the PUBLIC, sanitized source package. Its historical v1
        # certificate binds the PRIVATE source, not these public bytes. The
        # separate public manifest records the sanctioned filename/path edits.
        manifest_path = self.bundle.parent / "PUBLIC_RELEASE_MANIFEST.json"
        _require(manifest_path.is_file(), "native_sol_manifest_missing")
        manifest = json.loads(manifest_path.read_bytes())
        _require(manifest.get("historical_sol_certificate_refers_to_original_private_bundle") is True
                 and manifest.get("runtime_activation") is False
                 and manifest.get("public_bundle_is_exact_unmodified_source_subset") is False,
                 "native_sol_public_manifest_invalid")
        files = manifest.get("artifacts")
        _require(isinstance(files, dict), "native_sol_manifest_invalid")
        for member in (*_SOURCE_FILES, "certificate.json"):
            entry = files.get("sol61/" + member)
            path = self.bundle / member
            expected = entry.get("sha256") if isinstance(entry, dict) else None
            _require(isinstance(expected, str) and _SHA.fullmatch(expected) is not None
                     and path.is_file() and _sha(path.read_bytes()) == expected,
                     "native_sol_public_source_hash_mismatch")
        self.public_source_manifest_sha256 = _sha(manifest_path.read_bytes())
        spec = importlib.util.spec_from_file_location("b66_sol61_4117", self.engine_file)
        _require(spec is not None and spec.loader is not None,
                 "native_sol_engine_unavailable")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.engine = module.SolMultipage(self.bundle / "template", node)

    def _changes(self, model: dict[str, Any]) -> dict[str, Any]:
        _require(model.get("schemaVersion") == 1 and
                 model.get("derivedBy") == "quote-core" and
                 isinstance(model.get("coreTotals"), dict) and
                 isinstance(model.get("facts"), dict) and
                 isinstance(model.get("items"), list) and
                 isinstance(model.get("totals"), dict) and
                 isinstance(model.get("writtenWords"), str) and
                 model.get("taxReview") == {"required": False},
                 "native_sol_model_invalid")
        facts = model["facts"]
        meta = facts.get("meta")
        sender = facts.get("sender")
        recipient = facts.get("recipient")
        _require(isinstance(meta, dict) and isinstance(sender, dict) and
                 isinstance(recipient, dict), "native_sol_facts_invalid")
        baseline = self.engine.build_slots({})["draft"]
        # The fixed certified CGI artwork contains the original sender and tax
        # policy. A user-facing claim that differs would misrepresent the PDF.
        for name in ("company", "rep", "contactPerson", "bizNo", "address", "phone", "email"):
            _require(sender.get(name) == baseline["sender"].get(name),
                     "native_sol_sender_mismatch")
        for name in ("person", "address", "email"):
            _require(recipient.get(name, "") == baseline["recipient"].get(name, ""),
                     "native_sol_recipient_unsupported")
        _require(meta.get("validDays") == baseline["meta"]["validDays"] and
                 facts.get("taxRateText") == "10%", "native_sol_tax_policy_mismatch")
        for field in ("quoteNo", "issueDate", "projectName"):
            _require(isinstance(meta.get(field), str) and meta[field],
                     "native_sol_meta_invalid")
        _require(isinstance(recipient.get("company"), str) and recipient["company"],
                 "native_sol_recipient_invalid")
        totals = model["coreTotals"]
        _require(totals.get("mode") == "EXCLUSIVE" and
                 totals.get("detailGroups") == [] and
                 "calculationPolicy" not in totals and "roundingAdjustment" not in totals,
                 "native_sol_calculation_policy_unsupported")
        source_rows = totals.get("effectiveItems")
        _require(isinstance(source_rows, list) and
                 1 <= len(source_rows) <= 100, "native_sol_items_invalid")
        changes: dict[str, Any] = {
            "recipient": recipient["company"], "project": meta["projectName"],
            "issueDate": meta["issueDate"], "quoteNo": meta["quoteNo"], "items": [],
        }
        for row in source_rows:
            _require(isinstance(row, dict), "native_sol_items_invalid")
            candidate = {k: row.get(k, "") for k in ("name", "spec", "unit", "note")}
            candidate["qty"] = row.get("qty")
            candidate["unitPrice"] = row.get("unitPrice")
            changes["items"].append(candidate)
        return changes

    def render_pdf(self, **_kwargs: Any) -> dict[str, Any]:
        # Deliberately never satisfies the authenticated route's render_pdf
        # contract. The public v1 manifest explicitly says runtime_activation=false
        # and the historical certificate belongs to the private original bundle.
        raise NativeSolRejected("native_sol_public_release_not_certified")

    def render_candidate(self, render_model: dict[str, Any]) -> dict[str, Any]:
        """Render offline technical evidence only; NO certification headers."""
        _require(isinstance(render_model, dict) and
                 isinstance(render_model.get("template"), dict) and
                 render_model["template"].get("approved") is True and
                 not render_model["template"].get("fallbackReason"),
                 "native_sol_template_invalid")
        changes = self._changes(render_model)
        rows = len(changes["items"])
        derived = self.engine.build_slots(changes)
        computed = derived["totals"]
        submitted = render_model["coreTotals"]
        for field in ("subtotal", "supply", "vat", "grand", "mode", "amounts"):
            _require(type(submitted.get(field)) is type(computed.get(field)) and
                     submitted[field] == computed[field],
                     "native_sol_quote_core_mismatch")
        _require(len(computed["effectiveItems"]) == len(submitted["effectiveItems"]),
                 "native_sol_quote_core_mismatch")
        for real, requested in zip(computed["effectiveItems"], submitted["effectiveItems"]):
            for field in ("name", "qty", "unitPrice", "spec", "unit", "note"):
                _require(real.get(field, "") == requested.get(field, ""),
                         "native_sol_quote_core_mismatch")
        _require(f'일금 {render_model["writtenWords"]}원정' in
                 derived["slots"]["grandWrittenLine"], "native_sol_words_mismatch")
        for name, number in (("subtotalText", computed["supply"]),
                             ("vatText", computed["vat"]),
                             ("grandText", computed["grand"])):
            _require(_money_display(render_model["totals"].get(name), f"{number:,}"),
                     "native_sol_totals_projection_mismatch")
        display_rows = [row for row in render_model["items"]
                        if isinstance(row, dict) and row.get("filler") is not True]
        _require(len(display_rows) == rows, "native_sol_item_projection_mismatch")
        for index, row in enumerate(display_rows):
            values = row.get("values")
            _require(isinstance(values, dict), "native_sol_item_projection_mismatch")
            for key, field in (("name", "Name"), ("spec", "Spec"),
                               ("unit", "Unit"), ("note", "Note")):
                _require(values.get(key, "") == derived["slots"][f"item{index}{field}"],
                         "native_sol_item_projection_mismatch")
            for key, field in (("qty", "Qty"), ("unitPrice", "UnitPrice"),
                               ("amount", "Amount")):
                shown = values.get(key)
                expected = derived["slots"][f"item{index}{field}"]
                _require((_qty_display(shown, expected) if key == "qty"
                          else _money_display(shown, expected)),
                         "native_sol_item_projection_mismatch")
        with tempfile.TemporaryDirectory(prefix="b66-native-sol-") as temp:
            output = Path(temp) / "quote.pdf"
            result = self.engine.render(output, changes)
            pdf = output.read_bytes()
        _require(len(pdf) <= 32 * 1024 * 1024 and pdf.startswith(b"%PDF-"),
                 "native_sol_pdf_invalid")
        reader = PdfReader(io.BytesIO(pdf), strict=True)
        pages = len(reader.pages)
        _require(pages == result["pages"] and _sha(pdf) == result["pdfSha256"]
                 and (rows > 3 or pages == 1),
                 "native_sol_pdf_integrity_failed")
        return {
            "certified": False, "releaseEligible": False,
            "sourceManifestSha256": self.public_source_manifest_sha256,
            "pdf": pdf, "pdfSha256": _sha(pdf), "pageCount": pages,
            "itemCount": rows,
        }
