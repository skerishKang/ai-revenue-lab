"""#8953 3b: CGI-only real PowerShell -> bounded PDF/XLSX selection child.

Pytest temp data never leaves the test-only directory. No real registered PC
or operator folder is accessed, and the test sets its own PYTHONPATH.
"""
from __future__ import annotations
import io
import json
import os
import subprocess
import shutil
from pathlib import Path
import pytest

from app.claw_pc_read_command import pc_read_chunk_command
from app.claw_pc_document_read import (
    PC_DOCUMENT_MAX_BYTES, PC_DOCUMENT_RESPONSE_MAX_BYTES, valid_xlsx_range,
)

POWERSHELL = shutil.which("powershell.exe") or shutil.which("powershell")
ROOT = Path(__file__).resolve().parents[3]
PY = Path(r"D:\padiem-work\claw-general\_venv\Scripts")
PY_MODULES = os.pathsep.join((
    str(ROOT / "apps/korean-ai-code-agent/src"),
    str(ROOT / "packages/padiem-ai-core"),
))


def pdf_bytes(*texts: str, encrypt=False):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer=PdfWriter()
    for text in texts:
        page=writer.add_blank_page(width=612,height=792)
        font=DictionaryObject({NameObject("/Type"):NameObject("/Font"),
              NameObject("/Subtype"):NameObject("/Type1"),
              NameObject("/BaseFont"):NameObject("/Helvetica")})
        page[NameObject("/Resources")]=DictionaryObject({
            NameObject("/Font"):DictionaryObject({NameObject("/F1"):writer._add_object(font)})})
        stream=DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 20 700 Td ({text}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")]=writer._add_object(stream)
    if encrypt:
        writer.encrypt("synthetic-secret-only")
    out=io.BytesIO()
    writer.write(out)
    return out.getvalue()


def workbook_bytes():
    from openpyxl import Workbook
    book=Workbook()
    a=book.active
    a.title="견적서"
    a["A1"]="항목"
    a["B1"]="단위"
    a["C1"]="계산식"
    a["A2"]="랜선"
    a["B2"]=12
    a["C2"]="=B2*2"
    book.create_sheet("다른시트")["A1"]="not selected"
    out=io.BytesIO()
    book.save(out)
    return out.getvalue()


def run_pc(tmp_path, name, content, selector, *, extractor=True):
    assert POWERSHELL, "Windows PowerShell required"
    path=tmp_path/name
    if content is not None:
        path.write_bytes(content)
    script=pc_read_chunk_command(root=str(tmp_path),relative=name,**selector)
    assert "ReparsePoint" in script and "document_selection_child" in script
    assert "16000000" not in script
    command=tmp_path/"read-document.ps1"
    command.write_text(script,encoding="utf-8-sig")
    env=os.environ.copy()
    env["PATH"]=str(PY)+os.pathsep+env.get("PATH","")
    env["PYTHONPATH"]=PY_MODULES if extractor else str(tmp_path)
    env["PYTHONDONTWRITEBYTECODE"]="1"
    result=subprocess.run(
       [POWERSHELL,"-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass",
        "-File",str(command)],
       env=env,capture_output=True,timeout=90,check=True,
    )
    output=result.stdout.decode("utf-8-sig")
    payload=[line for line in output.splitlines() if line.strip()]
    assert len(payload)==1,(payload[-4:],result.stderr[-500:])
    assert len(payload[0].encode("utf-8"))<=PC_DOCUMENT_RESPONSE_MAX_BYTES
    return json.loads(payload[0])


@pytest.mark.skipif(not POWERSHELL,reason="Windows PowerShell required")
def test_selected_pdf_pages_are_original_numbers_and_can_resume(tmp_path):
    data=pdf_bytes("FIRST","SECOND","THIRD","FOURTH")
    first=run_pc(tmp_path,"trial.pdf",data,{"page":2,"page_count":2})
    assert first["ok"] is True,first
    assert [x["page"] for x in first["pages"]]==[2,3]
    assert first["pages"][0]["text"]=="SECOND"
    assert first["next_cursor"]==4
    assert first["truncated"] is True and first["truncation_reason"]=="page_count_limit"
    assert first["source_complete"] is True
    last=run_pc(tmp_path,"trial.pdf",data,{"page":first["next_cursor"],"page_count":10})
    assert last["ok"] is True and [x["page"] for x in last["pages"]]==[4]
    assert last["has_more"] is False and last["eof"] is True


@pytest.mark.skipif(not POWERSHELL,reason="Windows PowerShell required")
def test_excel_sheet_range_addresses_cached_value_and_formula(tmp_path):
    data=workbook_bytes()
    row=run_pc(tmp_path,"trial.xlsx",data,{"sheet":"견적서","cell_range":"A1:C2"})
    assert row["ok"] is True,row
    assert row["sheet"]=="견적서" and row["range"]=="A1:C2"
    assert row["cell_count"]==6 and row["cells"][-1]["formula"]=="=B2*2"
    assert row["cells"][3]=={"cell":"A2","value":"랜선"}
    assert row["cells"][4]=={"cell":"B2","value":"12"}
    assert "다른시트" not in row["text"]
    assert row["source_complete"] is True and row["eof"] is True


@pytest.mark.skipif(not POWERSHELL,reason="Windows PowerShell required")
def test_pdf_scanned_encrypted_and_missing_parser_are_closed(tmp_path):
    from pypdf import PdfWriter
    writer=PdfWriter()
    writer.add_blank_page(width=100,height=100)
    buf=io.BytesIO()
    writer.write(buf)
    assert run_pc(tmp_path,"trial.pdf",buf.getvalue(),{"page":1,"page_count":1})=={
        "ok":False,"error":"ocr_required"}
    assert run_pc(tmp_path,"trial.pdf",pdf_bytes("ONE",encrypt=True),{"page":1,"page_count":1})=={
        "ok":False,"error":"encrypted"}
    missing=run_pc(tmp_path,"trial.pdf",pdf_bytes("ONE"),
                  {"page":1,"page_count":1},extractor=False)
    assert missing=={"ok":False,"error":"extractor_unavailable"}


@pytest.mark.skipif(not POWERSHELL,reason="Windows PowerShell required")
def test_source_limit_never_parses_a_silent_prefix(tmp_path):
    path=tmp_path/"trial.pdf"
    with path.open("wb") as stream:
        stream.write(b"%PDF-")
        stream.seek(PC_DOCUMENT_MAX_BYTES)
        stream.write(b"x")
    assert path.stat().st_size==PC_DOCUMENT_MAX_BYTES+1
    result=run_pc(tmp_path,"trial.pdf",None,{"page":1,"page_count":1})
    assert result=={"ok":False,"error":"source_limit_exceeded"}
    assert path.stat().st_size==PC_DOCUMENT_MAX_BYTES+1


@pytest.mark.skipif(not POWERSHELL,reason="Windows PowerShell required")
def test_xlsx_larger_than_16mib_is_parsed_only_from_complete_zip(tmp_path):
    import zipfile
    raw=workbook_bytes()
    data=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source:
        with zipfile.ZipFile(data,"w") as dest:
            for member in source.infolist():
                dest.writestr(member,source.read(member))
            # This is an authenticated test-owned fixture, not an arbitrary
            # user's file. The old 16 MiB prefix has no central ZIP footer.
            dest.writestr("xl/media/padding.bin",os.urandom(17*1024*1024),
                          compress_type=zipfile.ZIP_STORED)
    assert len(data.getvalue())>16*1024*1024
    output=run_pc(tmp_path,"trial.xlsx",data.getvalue(),
                  {"sheet":"견적서","cell_range":"A2:C2"})
    assert output["ok"] is True,output
    assert output["cells"][0]["value"]=="랜선"
    assert output["size_bytes"]==len(data.getvalue())


def test_reject_unbounded_or_mixed_selectors_before_any_pc_script():
    from padiem_ai_core.pc_document_selectors import (
        valid_pdf_selection,valid_xlsx_selection)
    assert valid_pdf_selection(1,10)
    assert not valid_pdf_selection(1,11)
    assert not valid_pdf_selection(True,1)
    assert valid_xlsx_range("A1:D30")
    assert valid_xlsx_selection("견적서","A1:D30")
    assert not valid_xlsx_selection("견적서","A1:Z100")
    for selector in (
        {"page":0,"page_count":1},
        {"page":1,"page_count":11},
        {"page":1,"page_count":1,"offset":0,"length":100},
        {"sheet":"견적서","cell_range":"A1:Z100"},
        {"sheet":"견적서","cell_range":"C3:A1"},
    ):
        with pytest.raises(ValueError):
            pc_read_chunk_command(root="C:/trial",relative="trial.pdf" if "page" in selector
                                  else "trial.xlsx",**selector)
