"""#8953 3b: isolated, path-free PDF page and XLSX rectangle tests."""
from __future__ import annotations
import base64
from io import BytesIO
import json
import subprocess
import sys

import pytest
from kagent.document_selection_child import (
    select_document, MAX_SELECTION_REPORT_BYTES, MAX_SELECTION_SOURCE_BYTES,
)


def pdf_bytes(*labels: str, encrypt: bool = False) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import (
        DictionaryObject, NameObject, DecodedStreamObject,
    )
    writer = PdfWriter()
    for label in labels:
        page = writer.add_blank_page(width=612, height=792)
        resources = DictionaryObject()
        font = DictionaryObject()
        font[NameObject("/Type")] = NameObject("/Font")
        font[NameObject("/Subtype")] = NameObject("/Type1")
        font[NameObject("/BaseFont")] = NameObject("/Helvetica")
        font_ref = writer._add_object(font)
        fonts = DictionaryObject()
        fonts[NameObject("/F1")] = font_ref
        resources[NameObject("/Font")] = fonts
        page[NameObject("/Resources")] = resources
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 16 Tf 72 720 Td ({label}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypt:
        writer.encrypt("private-test-only-password")
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def pdf_request(data: bytes, *, page=1, page_count=1):
    return {"name":"trial.pdf","media_type":"application/pdf",
            "base64":base64.b64encode(data).decode("ascii"),
            "page":page,"page_count":page_count}


def workbook_bytes():
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.title = "내역"
    sheet["A1"] = "품목"
    sheet["B1"] = "수량"
    sheet["C1"] = "계산식"
    sheet["A2"] = "케이블"
    sheet["B2"] = 3
    sheet["C2"] = "=B2*2"
    sheet2 = book.create_sheet("보조")
    sheet2["A1"] = "보조 시트"
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def xlsx_request(data: bytes, *, sheet="내역", cell_range="A1:C2"):
    return {"name":"trial.xlsx",
            "media_type":"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "base64":base64.b64encode(data).decode("ascii"),
            "sheet":sheet,"range":cell_range}


def test_pdf_returns_original_page_numbers_and_reusable_next_cursor():
    data = pdf_bytes("PDF_ONE","PDF_TWO","PDF_THREE","PDF_FOUR")
    first=select_document(pdf_request(data,page=2,page_count=2))
    assert first["ok"] is True, first
    assert first["unit"]=="pages" and first["total_pages"]==4
    assert [x["page"] for x in first["pages"]] == [2,3]
    assert ["PDF_TWO","PDF_THREE"] == [x["text"] for x in first["pages"]]
    assert first["has_more"] is True and first["truncated"] is True
    assert first["truncation_reason"]=="page_count_limit"
    assert first["next_cursor"]==4 and first["source_complete"] is True
    assert first["eof"] is False and first["partial"] is False
    assert first["size_bytes"]==len(data)
    last=select_document(pdf_request(data,page=first["next_cursor"],page_count=10))
    assert last["ok"] is True
    assert [x["page"] for x in last["pages"]]==[4]
    assert last["eof"] is True and last["next_cursor"] is None
    assert len(json.dumps(first,ensure_ascii=False).encode())<=MAX_SELECTION_REPORT_BYTES


def test_pdf_scanned_and_encrypted_and_out_of_range_are_explicit():
    from pypdf import PdfWriter
    blank=PdfWriter()
    blank.add_blank_page(width=120,height=180)
    out=BytesIO()
    blank.write(out)
    assert select_document(pdf_request(out.getvalue()))=={"ok":False,"error":"ocr_required"}
    secure=pdf_bytes("SECRET",encrypt=True)
    assert select_document(pdf_request(secure))=={"ok":False,"error":"encrypted"}
    assert select_document(pdf_request(pdf_bytes("ONE"),page=3))=={
        "ok":False,"error":"page_out_of_range"}


def test_pdf_selected_page_text_over_response_limit_fails_instead_of_truncating_page():
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer=PdfWriter()
    page=writer.add_blank_page(width=612,height=792)
    font=DictionaryObject({NameObject("/Type"):NameObject("/Font"),
                           NameObject("/Subtype"):NameObject("/Type1"),
                           NameObject("/BaseFont"):NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"):DictionaryObject({NameObject("/F1"):writer._add_object(font)})})
    stream=DecodedStreamObject()
    # Multiple PDF text objects, each within pypdf parsing limits.
    stream.set_data((b"BT /F1 14 Tf 20 700 Td ("+b"A"*5000+b") Tj ET\n")*70)
    page[NameObject("/Contents")]=writer._add_object(stream)
    out=BytesIO()
    writer.write(out)
    assert select_document(pdf_request(out.getvalue()))=={
        "ok":False,"error":"page_too_large"}


def test_xlsx_exact_cells_formula_and_sheet_name():
    data=workbook_bytes()
    result=select_document(xlsx_request(data))
    assert result["ok"] is True, result
    assert result["unit"]=="cells" and result["sheet"]=="내역"
    assert result["range"]=="A1:C2" and result["cell_count"]==6
    assert [x["cell"] for x in result["cells"]]==["A1","B1","C1","A2","B2","C2"]
    assert result["cells"][3]["value"]=="케이블"
    assert result["cells"][4]["value"]=="3"
    assert result["cells"][5]["formula"]=="=B2*2"
    assert result["cells"][5]["value"]==""
    assert "(no cached value)" in result["text"]
    assert result["eof"] is True and result["has_more"] is False
    assert result["truncated"] is False and result["next_cursor"] is None
    assert result["source_complete"] is True
    second=select_document(xlsx_request(data,sheet="보조",cell_range="A1:A1"))
    assert second["cells"]==[{"cell":"A1","value":"보조 시트"}]
    assert select_document(xlsx_request(data,sheet="없는시트"))=={
        "ok":False,"error":"sheet_not_found"}


def test_xlsx_bounds_and_invalid_or_mixed_selection_fail():
    data=workbook_bytes()
    assert select_document(xlsx_request(data,cell_range="A1:Z100"))=={
        "ok":False,"error":"cell_limit_exceeded"}
    for expr in ("A1:Z0","A1:XFE5","XFD1:XFE1","C10:A1","A0:A2","A1:D2000000"):
        assert select_document(xlsx_request(data,cell_range=expr))=={
            "ok":False,"error":"range_invalid"}
    request=xlsx_request(data)
    request["page"]=1
    assert select_document(request)=={"ok":False,"error":"range_invalid"}


def test_xlsx_large_cells_returns_whole_row_continuation_without_loss():
    from openpyxl import Workbook
    book=Workbook()
    sheet=book.active
    sheet.title="데이터"
    for row in range(1,10):
        for col in range(1,3):
            sheet.cell(row,col).value = "값" * 14000 + str(row)
    out=BytesIO()
    book.save(out)
    first=select_document(xlsx_request(out.getvalue(),sheet="데이터",cell_range="A1:B9"))
    assert first["ok"] is True, first
    assert first["truncated"] is True and first["truncation_reason"]=="response_bytes_limit"
    assert first["next_cursor"].startswith("A") and first["next_cursor"].endswith(":B9")
    assert first["cell_count"] % 2 == 0
    assert len(json.dumps(first,ensure_ascii=False,separators=(",",":")).encode())<=256*1024
    all_cells = [x["cell"] for x in first["cells"]]
    cursor = first["next_cursor"]
    pages = 1
    while cursor:
        assert pages < 10, "Continuation cannot loop or repeat a row"
        page = select_document(xlsx_request(out.getvalue(), sheet="데이터", cell_range=cursor))
        assert page["ok"] is True, page
        all_cells.extend(x["cell"] for x in page["cells"])
        pages += 1
        cursor = page["next_cursor"]
    assert len(all_cells) == 18 and len(set(all_cells)) == 18


def test_parser_unavailable_is_closed(monkeypatch):
    import sys as namespace
    data=workbook_bytes()
    monkeypatch.setitem(namespace.modules,"openpyxl",None)
    assert select_document(xlsx_request(data))=={"ok":False,"error":"extractor_unavailable"}


def test_isolated_child_stdin_stdout_contract():
    request=pdf_request(pdf_bytes("ISOLATED"),page=1,page_count=1)
    encoded=json.dumps(request,ensure_ascii=False).encode()
    out=subprocess.run(
        [sys.executable,"-P","-m","kagent.document_selection_child"],
        input=encoded,capture_output=True,check=True,timeout=30,
    )
    assert out.returncode==0 and not out.stderr
    answer=json.loads(out.stdout)
    assert answer["pages"]==[{"page":1,"text":"ISOLATED"}]
    assert len(out.stdout)<=256*1024


def test_no_host_path_or_network_authority_source_contract():
    from pathlib import Path
    import inspect
    import kagent.document_selection_child as child
    source=inspect.getsource(child)
    assert 'open(' not in source.replace("load_workbook(","")
    assert "import subprocess" not in source
    assert "import requests" not in source
    assert "import socket" not in source
    assert "os.system" not in source
    assert "MAX_SELECTION_SOURCE_BYTES = 64 * 1024 * 1024" in source
