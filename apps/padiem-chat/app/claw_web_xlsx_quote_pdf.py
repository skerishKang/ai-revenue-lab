"""#3933 WEB-FIRST owner-only supported quote PDF via Cloudflare Browser Rendering.

Print a clearly labelled standard quote PDF, NOT a pixel-identical Excel
workbook. Reject rich sheets rather than silently dropping rows or drawings.
No URL fetches; HTML derived only from owner-scoped verified revised XLSX.
"""
from __future__ import annotations
import hashlib
import html
import inspect
from decimal import Decimal
from urllib.parse import quote
from starlette.requests import Request
from starlette.responses import Response

from .claw_web_xlsx_quote_editor import (
    MAIN, _load, _cells, _money, WebQuoteEditUnsupported,
)
from .claw_web_xlsx_quote_write_routes import (
    web_xlsx_quote_edit_download, _confirmed, _error, _NO_STORE,
)
from .service_binding_response import read_bounded_service_binding_body

PATH = "/api/claw/office/web-selections/{selection_ref}/quote-edit/pdf"
PDF_MAX = 4_194_304
ALLOWED_CELLS = frozenset({"A1", "B4", "B5", "B6", "B7"})


def supported_quote_print_html(xlsx: bytes, *, expected_sha256: str,
                               school_name: str, supply_amount: int) -> str:
    if (type(xlsx) is not bytes or type(expected_sha256) is not str
            or hashlib.sha256(xlsx).hexdigest() != expected_sha256):
        raise WebQuoteEditUnsupported("PDF_SOURCE_INTEGRITY_FAILED")
    parts, sheet = _load(xlsx)
    cells = _cells(sheet)
    if (set(cells) != ALLOWED_CELLS
            or {m.get("ref") for m in sheet.iter(MAIN+"mergeCell")} != {"A1:D1"}
            or any(n is not None for n in (
                sheet.find(MAIN+"printOptions"), sheet.find(MAIN+"sheetPr"),
                sheet.find(MAIN+"pageSetup"), sheet.find(MAIN+"headerFooter"),
                sheet.find(MAIN+"pageMargins"),
            ))):
        raise WebQuoteEditUnsupported("PDF_PRINT_LAYOUT_NOT_CERTIFIED")
    header = cells["A1"]
    celltext = header.find(MAIN+"is/"+MAIN+"t")
    if (header.get("t") != "inlineStr" or celltext is None
            or celltext.text != school_name
            or len(school_name) > 120):
        raise WebQuoteEditUnsupported("PDF_SCHOOL_CELL_MISMATCH")
    price, vat_rate = (_money(cells[k]) for k in ("B4", "B5"))
    # B6/B7 are formula cells: _money intentionally rejects formulas.
    # Read their immutable cached values and verify exact formula + parity.
    try:
        tax = Decimal(cells["B6"].find(MAIN+"v").text)
        total = Decimal(cells["B7"].find(MAIN+"v").text)
    except (AttributeError, TypeError, ValueError) as exc:
        raise WebQuoteEditUnsupported("PDF_FORMULA_CACHE_INVALID") from exc
    if (not tax.is_finite() or not total.is_finite()
            or price != Decimal(supply_amount) or vat_rate != Decimal("0.1")
            or tax != price/10 or total != price+tax):
        raise WebQuoteEditUnsupported("PDF_VALUE_PARITY_FAILED")
    if (cells["B6"].find(MAIN+"f").text != "B4*B5"
            or cells["B7"].find(MAIN+"f").text != "SUM(B4,B6)"):
        raise WebQuoteEditUnsupported("PDF_FORMULA_PARITY_FAILED")
    money = lambda n: f"{int(n):,}"
    safe_name = html.escape(school_name, quote=True)
    # No remote stylesheets, fonts, scripts, links or user-supplied HTML.
    return ("""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'">
<style>
@page{size:A4 portrait;margin:22mm 18mm}
*{box-sizing:border-box}
body{font-family:"Noto Sans CJK KR","Malgun Gothic",sans-serif;color:#192734;margin:0;font-size:12pt}
h1{text-align:center;font-size:23pt;letter-spacing:0.3em;margin:8mm 0 13mm;font-weight:700}
.meta{border-top:3px solid #253b51;padding:5mm 1mm 8mm;margin-bottom:9mm}
.meta b{font-size:15pt}
table{border-collapse:collapse;width:100%;table-layout:fixed}
td,th{border:1px solid #7c8791;padding:11pt 8pt}
th{background:#f3f5f7;text-align:left;width:46%;font-weight:500}
td.amount{text-align:right;font-variant-numeric:tabular-nums}
.total th,.total td{background:#eef4f8;font-weight:700;font-size:14pt}
.note{font-size:9pt;color:#57616a;margin-top:12mm;line-height:1.7}
</style></head><body><h1>견 적 서</h1><div class="meta">수신 <b>"""
            + safe_name + """</b> 귀중</div><table aria-label="견적금액">
<tr><th>공급가액 (원)</th><td class="amount">"""
            + money(price) + """</td></tr>
<tr><th>부가가치세 (10%)</th><td class="amount">"""
            + money(tax) + """</td></tr>
<tr class="total"><th>합계금액 (원)</th><td class="amount">"""
            + money(total) + """</td></tr></table>
<p class="note">Hark 표준 견적 요약 PDF · 승인된 단일 시트의 금액과 수신처를 재검증하여 출력했습니다.<br>
원본 Excel 서식과 동일한 인쇄본이 필요한 경우 XLSX 파일을 사용하세요.</p>
</body></html>""")


class BrowserQuotePdfRenderer:
    """Uses operator provisioned Cloudflare Browser Rendering Quick Action."""

    def __init__(self, browser_binding):
        if not callable(getattr(browser_binding, "quickAction", None)):
            raise ValueError("Cloudflare BROWSER binding required")
        self._browser = browser_binding

    async def render(self, document: str) -> bytes:
        if (type(document) is not str or not 100 <= len(document.encode("utf-8")) <= 8192
                or "<!doctype html>" not in document
                or '<meta http-equiv="Content-Security-Policy"' not in document):
            raise ValueError("bounded static printable HTML required")
        response = self._browser.quickAction("pdf", {"html": document})
        if inspect.isawaitable(response):
            response = await response
        if (int(getattr(response, "status", 0)) != 200):
            raise ValueError("browser renderer failed")
        raw = await read_bounded_service_binding_body(
            response, max_bytes=PDF_MAX, allow_text_fallback=False,
        )
        if (len(raw) < 128 or not raw.startswith(b"%PDF-")
                or b"%%EOF" not in raw[-1024:]):
            raise ValueError("invalid PDF renderer output")
        return raw


async def web_xlsx_quote_pdf_download(request: Request) -> Response:
    context = await _confirmed(request)
    if isinstance(context, Response):
        return context
    _store, receipt, _owner, _workspace, _ref = context
    renderer = getattr(request.app.state, "web_xlsx_quote_pdf_renderer", None)
    if (getattr(request.app.state, "web_xlsx_quote_pdf_enabled", False) is not True
            or not callable(getattr(renderer, "render", None))):
        return _error(503, "web_xlsx_quote_pdf_renderer_unavailable")
    if receipt.get("state") != "confirmed":
        return _error(404, "web_xlsx_quote_pdf_revision_not_approved")
    # Calls the EXACT same read-only owner-scoped revision integrity checks
    # as XLSX download. No browser-supplied object ID or arbitrary source.
    xlsx = await web_xlsx_quote_edit_download(request)
    if xlsx.status_code != 200 or type(xlsx.body) is not bytes:
        return xlsx
    try:
        document = supported_quote_print_html(
            xlsx.body, expected_sha256=receipt["revision_sha256"],
            school_name=receipt["school_name"],
            supply_amount=receipt["supply_amount"],
        )
    except (WebQuoteEditUnsupported, ValueError, TypeError, KeyError, AttributeError):
        return _error(422, "web_xlsx_quote_pdf_unsupported_print_layout")
    try:
        pdf = renderer.render(document)
        if inspect.isawaitable(pdf):
            pdf = await pdf
        if type(pdf) is not bytes or not pdf.startswith(b"%PDF-") or len(pdf)>PDF_MAX:
            raise ValueError("pdf bytes invalid")
    except Exception:
        return _error(503, "web_xlsx_quote_pdf_render_failed")
    return Response(pdf, media_type="application/pdf", headers={
        **_NO_STORE, "Cross-Origin-Resource-Policy": "same-origin",
        "Vary": "Cookie", "X-Content-Type-Options": "nosniff",
        "Content-Disposition": "attachment; filename*=UTF-8''"
        + quote("hark-revised-quote-summary.pdf",safe=""),
    })
