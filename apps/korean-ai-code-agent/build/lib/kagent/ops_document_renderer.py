from __future__ import annotations

from dataclasses import dataclass
import hashlib
from html import escape
from typing import Any

from .contracts import ContractError
from .ops_documents import CustomerQuoteDocumentManifest, PurchaseOrderDocumentManifest

MAX_RENDERED_DOCUMENT_BYTES = 512_000


@dataclass(frozen=True, slots=True)
class RenderedBusinessDocument:
    document_number: str
    media_type: str
    utf8_bytes: bytes
    sha256: str

    def __post_init__(self) -> None:
        if self.media_type != "text/html; charset=utf-8":
            raise ContractError("M1 renderer supports deterministic UTF-8 HTML only")
        if not isinstance(self.utf8_bytes, bytes) or not self.utf8_bytes or len(self.utf8_bytes) > MAX_RENDERED_DOCUMENT_BYTES:
            raise ContractError("rendered document must be non-empty and bounded")
        expected = hashlib.sha256(self.utf8_bytes).hexdigest()
        if self.sha256 != expected:
            raise ContractError("rendered document SHA-256 mismatch")

    def safe_dict(self) -> dict[str, Any]:
        return {
            "document_number": self.document_number,
            "media_type": self.media_type,
            "size_bytes": len(self.utf8_bytes),
            "sha256": self.sha256,
            "body_exposed": False,
            "network_fetch": False,
            "script_execution": False,
            "arbitrary_template": False,
        }


def _money_html(value: dict[str, Any]) -> str:
    amount = value.get("amount_minor")
    currency = value.get("currency")
    if isinstance(amount, bool) or not isinstance(amount, int) or not isinstance(currency, str):
        raise ContractError("manifest money shape is invalid")
    return f"{escape(currency)} {amount}"


def _row(cells: list[str]) -> str:
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


def _shell(*, title: str, number: str, issue_date: str, body: str) -> bytes:
    html = (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>"
        + escape(title)
        + "</title></head><body><main>"
        + f"<h1>{escape(title)}</h1><p>Document: {escape(number)}</p><p>Issue date: {escape(issue_date)}</p>"
        + body
        + "</main></body></html>"
    )
    encoded = html.encode("utf-8")
    if len(encoded) > MAX_RENDERED_DOCUMENT_BYTES:
        raise ContractError("rendered document exceeds size limit")
    return encoded


class DeterministicHtmlBusinessDocumentRenderer:
    def render(self, manifest: CustomerQuoteDocumentManifest | PurchaseOrderDocumentManifest) -> RenderedBusinessDocument:
        if isinstance(manifest, CustomerQuoteDocumentManifest):
            body = self._render_customer_quote(manifest)
            title = "Customer Quotation"
        elif isinstance(manifest, PurchaseOrderDocumentManifest):
            body = self._render_purchase_order(manifest)
            title = "Purchase Order"
        else:
            raise ContractError("renderer accepts typed business document manifests only")
        payload = _shell(
            title=title,
            number=manifest.document_number,
            issue_date=manifest.issue_date.isoformat(),
            body=body,
        )
        return RenderedBusinessDocument(
            document_number=manifest.document_number,
            media_type="text/html; charset=utf-8",
            utf8_bytes=payload,
            sha256=hashlib.sha256(payload).hexdigest(),
        )

    @staticmethod
    def _render_customer_quote(manifest: CustomerQuoteDocumentManifest) -> str:
        rows: list[str] = []
        for item in manifest.lines:
            rows.append(
                _row(
                    [
                        escape(str(item["line_id"])),
                        escape(str(item["description"])),
                        escape(str(item["quantity"])),
                        escape(str(item["unit"])),
                        _money_html(item["sale_unit_price"]),
                        _money_html(item["sale_total"]),
                    ]
                )
            )
        return (
            f"<p>Customer: {escape(manifest.customer_id)}</p>"
            f"<p>{escape(manifest.title)}</p>"
            "<table><thead><tr><th>ID</th><th>Description</th><th>Qty</th><th>Unit</th><th>Unit price</th><th>Total</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
            + f"<p>Sale total: {_money_html(manifest.sale_total.safe_dict())}</p>"
        )

    @staticmethod
    def _render_purchase_order(manifest: PurchaseOrderDocumentManifest) -> str:
        rows: list[str] = []
        for item in manifest.lines:
            rows.append(
                _row(
                    [
                        escape(str(item["line_id"])),
                        escape(str(item["description"])),
                        escape(str(item["quantity"])),
                        escape(str(item["unit"])),
                        _money_html(item["unit_price"]),
                        _money_html(item["total"]),
                    ]
                )
            )
        return (
            f"<p>Supplier: {escape(manifest.supplier_id)}</p>"
            "<table><thead><tr><th>ID</th><th>Description</th><th>Qty</th><th>Unit</th><th>Unit price</th><th>Total</th></tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table>"
            + f"<p>Purchase total: {_money_html(manifest.purchase_total.safe_dict())}</p>"
        )


ARBITRARY_DOCUMENT_TEMPLATE_SUPPORTED = False
DOCUMENT_RENDER_NETWORK_FETCH_SUPPORTED = False
DOCUMENT_RENDER_SCRIPT_EXECUTION_SUPPORTED = False
REAL_PDF_RENDERER_CONFIGURED = False
