"""#3933 supported single-sheet summary PDF; verified owner revised XLSX only."""
from __future__ import annotations
import hashlib
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from pypdf import PdfWriter

sys.path.insert(0,str(Path(__file__).parent))
from test_3933_web_quote_write_gate import api,prepared,OWNER,FOREIGN,VALUES
from app.claw_web_xlsx_quote_pdf import (
    BrowserQuotePdfRenderer,supported_quote_print_html,WebQuoteEditUnsupported,
    PDF_MAX,
)
from app.claw_web_xlsx_quote_editor import revise_single_sheet_quote
from test_3933_web_quote_xlsx_editor import quote_fixture


class MemoryStream:
    def __init__(self, data):
        self.items=[data,None];self.cancelled=False
    async def read(self):
        x=self.items.pop(0)
        return SimpleNamespace(done=x is None,value=x)
    async def cancel(self):
        self.cancelled=True
    def releaseLock(self):
        pass

class MemoryBody:
    def __init__(self,data):self.data=data
    def getReader(self):return MemoryStream(self.data)

class Browser:
    def __init__(self,data=None):
        if data is None:
            buffer=BytesIO()
            writer=PdfWriter()
            writer.add_blank_page(width=595,height=842)
            writer.write(buffer)
            data=buffer.getvalue()
        self.data=data;self.requests=[]
    async def quickAction(self,action,opts):
        self.requests.append((action,opts))
        return SimpleNamespace(status=200,body=MemoryBody(self.data))


def html_for():
    sample=quote_fixture()
    revision=revise_single_sheet_quote(
        original=sample,original_sha256=hashlib.sha256(sample).hexdigest(),
        school_name="광주미래대학교",supply_amount=99_200_000)
    return revision


def test_pdf_template_reflects_approved_xlsx_values_without_remote_html_or_scripts():
    revised=html_for()
    markup=supported_quote_print_html(
        revised.revised_xlsx,expected_sha256=revised.revised_sha256,
        school_name="광주미래대학교",supply_amount=99_200_000)
    assert markup.startswith("<!doctype html>")
    assert "광주미래대학교" in markup
    assert "99,200,000" in markup
    assert "9,920,000" in markup
    assert "109,120,000" in markup
    assert "견 적 서" in markup
    assert "Excel" in markup
    assert "default-src 'none'" in markup
    assert "<script" not in markup and "https://" not in markup
    with pytest.raises(WebQuoteEditUnsupported,match="INTEGRITY"):
        supported_quote_print_html(
            revised.revised_xlsx,expected_sha256="f"*64,
            school_name="광주미래대학교",supply_amount=99_200_000)
    with pytest.raises(WebQuoteEditUnsupported,match="MISMATCH"):
        supported_quote_print_html(
            revised.revised_xlsx,expected_sha256=revised.revised_sha256,
            school_name="Foreign",supply_amount=99_200_000)
    with pytest.raises(WebQuoteEditUnsupported,match="PARITY"):
        supported_quote_print_html(
            revised.revised_xlsx,expected_sha256=revised.revised_sha256,
            school_name="광주미래대학교",supply_amount=99_200_010)


@pytest.mark.asyncio
async def test_true_binary_pdf_cloudflare_browser_binding_and_fail_closed():
    rendered=html_for()
    document=supported_quote_print_html(
        rendered.revised_xlsx,expected_sha256=rendered.revised_sha256,
        school_name="광주미래대학교",supply_amount=99_200_000)
    browser=Browser()
    pdf=await BrowserQuotePdfRenderer(browser).render(document)
    assert pdf.startswith(b"%PDF-")
    assert b"%%EOF" in pdf[-1024:]
    assert browser.requests[0][0]=="pdf"
    assert browser.requests[0][1]=={"html":document}
    for bad in (b"not a PDF"*20,b"%PDF-1.4"+b"x"*30,
                b"%PDF-1.7"+b"x"*(PDF_MAX+1)+b"%%EOF"):
        with pytest.raises(Exception):
            await BrowserQuotePdfRenderer(Browser(bad)).render(document)
    with pytest.raises(ValueError):
        BrowserQuotePdfRenderer(None)


@pytest.mark.asyncio
async def test_only_owner_approved_revised_xlsx_yields_summary_pdf(monkeypatch):
    app,settings,metadata,r2,db,history,selection,src,before,preview=await prepared(
        monkeypatch,enabled=True)
    ref=selection["selection_ref"]
    browser=Browser()
    app.state.web_xlsx_quote_pdf_renderer=BrowserQuotePdfRenderer(browser)
    app.state.web_xlsx_quote_pdf_enabled=True
    assert (await api(app,settings,ref,"pdf")).status_code==404
    done=await api(app,settings,ref,"commit",method="POST",
                   data={**VALUES,"edit_sha256":preview["edit_sha256"]})
    assert done.status_code==201,done.text
    assert (await api(app,settings,ref,"status")).json()["pdf_download_available"] is True
    pdf=await api(app,settings,ref,"pdf")
    assert pdf.status_code==200,pdf.text if pdf.status_code!=200 else ""
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert "attachment" in pdf.headers["content-disposition"]
    assert "no-store" in pdf.headers["cache-control"]
    assert pdf.content.startswith(b"%PDF-")
    assert len(browser.requests)==1
    assert browser.requests[0][0]=="pdf"
    assert "Gwangju University" in browser.requests[0][1]["html"]
    assert not any(k not in before and b"pdf" in v.lower() for k,v in r2.objects.items())
    assert (await api(app,settings,ref,"pdf",owner=FOREIGN)).status_code==404
    assert len(browser.requests)==1
    app.state.web_xlsx_quote_pdf_enabled=False
    assert (await api(app,settings,ref,"pdf")).status_code==503
    db.close()


@pytest.mark.asyncio
async def test_pdf_renderer_failure_does_not_expose_forged_bytes_or_modify_revision(monkeypatch):
    app,settings,metadata,r2,db,history,selection,src,before,preview=await prepared(
        monkeypatch,enabled=True)
    ref=selection["selection_ref"]
    done=await api(app,settings,ref,"commit",method="POST",
                   data={**VALUES,"edit_sha256":preview["edit_sha256"]})
    assert done.status_code==201
    app.state.web_xlsx_quote_pdf_enabled=True
    app.state.web_xlsx_quote_pdf_renderer=BrowserQuotePdfRenderer(Browser(b"invalid"))
    earlier=dict(r2.objects)
    result=await api(app,settings,ref,"pdf")
    assert result.status_code==503
    assert r2.objects==earlier
    # Existing owner Excel remains available even if Browser Rendering fails.
    excel=await api(app,settings,ref,"download")
    assert excel.status_code==200 and excel.content.startswith(b"PK")
    db.close()
