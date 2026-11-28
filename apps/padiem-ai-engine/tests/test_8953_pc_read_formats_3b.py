"""#8953 3b: signed Engine projection of page/cell selections is fail-closed."""
from __future__ import annotations
import json
import pytest
from app import claw_pc_query_step_driver as driver
from app.claw_pc_query_step_driver import _pc_chunk_projection, ToolHandlerError
from tests.test_6460_pc_chunk_read import (
    _install_wire, _chunk_handler, SUBJECT, RUN_ID, PRODUCT, DEVICE,
)


@pytest.fixture(autouse=True)
def _owner():
    t=driver._PC_QUERY_OWNER.set((SUBJECT,RUN_ID,PRODUCT,DEVICE))
    try:
        yield
    finally:
        driver._PC_QUERY_OWNER.reset(t)


def pdf_answer(**overrides):
    pages=[{"page":2,"text":"P2"},{"page":3,"text":"P3"}]
    result={"ok":True,"unit":"pages","size_bytes":1500,
            "total_pages":4,"page":2,"page_count":2,"pages":pages,
            "text":"[page 2]\nP2\n\n[page 3]\nP3",
            "eof":False,"partial":False,"truncated":True,
            "truncation_reason":"page_count_limit","has_more":True,
            "next_cursor":4,"source_complete":True}
    result.update(overrides)
    return json.dumps(result,ensure_ascii=False)


def xlsx_answer(**overrides):
    records=[
        {"cell":"A1","value":"품목"},{"cell":"B1","value":"합계"},
        {"cell":"A2","value":"랜선"},{"cell":"B2","value":"","formula":"=A1"},
    ]
    result={"ok":True,"unit":"cells","size_bytes":1400,"sheet":"견적서",
            "range":"A1:B2","cell_count":4,"cells":records,
            "text":"[견적서!A1] 품목\n[견적서!B1] 합계\n[견적서!A2] 랜선\n[견적서!B2] =A1 => (no cached value)",
            "eof":True,"partial":False,"truncated":False,
            "truncation_reason":None,"has_more":False,
            "next_cursor":None,"source_complete":True}
    result.update(overrides)
    return json.dumps(result,ensure_ascii=False)


def test_pdf_page_numbers_and_next_page_are_verified():
    p=_pc_chunk_projection(pdf_answer(),page=2,page_count=2)
    assert p["page"]==2 and p["total_pages"]==4
    assert [x["page"] for x in p["pages"]]==[2,3]
    assert p["next_cursor"]==4 and p["truncated"] is True
    assert p["eof"] is False and p["source_complete"] is True


def test_xlsx_cells_and_formulas_are_verified():
    p=_pc_chunk_projection(xlsx_answer(),sheet="견적서",cell_range="A1:B2")
    assert p["sheet"]=="견적서" and p["cell_count"]==4
    assert p["cells"][-1]["formula"]=="=A1"
    assert p["next_cursor"] is None and p["eof"] is True


@pytest.mark.parametrize("mutated",[
    {"page":3}, {"total_pages":2}, {"next_cursor":3},
    {"truncated":False}, {"has_more":False},{"source_complete":False},
    {"page_count":3},{"truncation_reason":"response_bytes_limit"},
    {"text":"fake"},{"partial":True},
    {"pages":[{"page":5,"text":"fake"}]},
])
def test_pdf_untrusted_response_is_not_projected_as_verified(mutated):
    with pytest.raises(ToolHandlerError):
        _pc_chunk_projection(pdf_answer(**mutated),page=2,page_count=2)


@pytest.mark.parametrize("mutated",[
    {"sheet":"Other"}, {"range":"A1:A1"}, {"cell_count":3},
    {"next_cursor":"B2"}, {"source_complete":False},
    {"truncated":True},{"eof":False}, {"text":"fake"},
    {"cells":[{"cell":"A1","value":"x"}]},
])
def test_xlsx_untrusted_response_is_not_projected_as_verified(mutated):
    with pytest.raises(ToolHandlerError):
        _pc_chunk_projection(xlsx_answer(**mutated),sheet="견적서",cell_range="A1:B2")


@pytest.mark.parametrize("error",["encrypted","ocr_required","source_limit_exceeded"])
def test_named_pdf_refusals_are_not_generic_successes(error):
    with pytest.raises(ToolHandlerError) as exc:
        _pc_chunk_projection(json.dumps({"ok":False,"error":error}),page=1,page_count=1)
    assert exc.value.code==error


def test_legacy_parser_unavailable_code_is_preserved():
    with pytest.raises(ToolHandlerError) as exc:
        _pc_chunk_projection(json.dumps({"ok":False,"error":"extractor_unavailable"}),
                             page=1,page_count=1)
    assert exc.value.code=="pc_chunk_extractor_unavailable"


@pytest.mark.asyncio
async def test_pdf_range_uses_only_verified_read_chunk_lane(monkeypatch):
    staged=[]
    _install_wire(monkeypatch,[pdf_answer()],captured=staged)
    result=await _chunk_handler()({"path":"trial.pdf","page":2,"page_count":2})
    assert staged[0]["op"]=="read_chunk"
    assert staged[0]["page"]==2 and staged[0]["page_count"]==2
    assert "offset" not in staged[0] and "start_line" not in staged[0]
    assert result["page"]==2 and result["next_cursor"]==4
    assert "pages" not in result  # page data appears only in bounded output
    assert json.loads(result["output"])["pages"][1]["page"] == 3


@pytest.mark.asyncio
async def test_xlsx_range_uses_only_verified_read_chunk_lane(monkeypatch):
    staged=[]
    _install_wire(monkeypatch,[xlsx_answer()],captured=staged)
    result=await _chunk_handler()({"path":"trial.xlsx","sheet":"견적서","range":"A1:B2"})
    assert staged[0]["op"]=="read_chunk"
    assert staged[0]["sheet"]=="견적서" and staged[0]["range"]=="A1:B2"
    assert "length" not in staged[0]
    assert result["cell_count"]==4 and result["source_complete"] is True


@pytest.mark.asyncio
async def test_mixed_invalid_and_oversized_selectors_are_denied_before_dispatch(monkeypatch):
    staged=[]
    _install_wire(monkeypatch,[],captured=staged)
    for args in (
        {"path":"x.pdf","page":0,"page_count":1},
        {"path":"x.pdf","page":1,"page_count":11},
        {"path":"x.pdf","page":True,"page_count":1},
        {"path":"x.pdf","page":1},
        {"path":"x.pdf","page":1,"page_count":1,"offset":0},
        {"path":"x.xlsx","sheet":"S","range":"A1:Z100"},
        {"path":"x.xlsx","sheet":"S","range":"C3:A1"},
        {"path":"x.xlsx","sheet":"S","range":"A1:D5","start_line":1,"line_count":4},
        {"path":"x.xlsx","sheet":"S"},
    ):
        with pytest.raises(ToolHandlerError):
            await _chunk_handler()(args)
    assert staged==[]


def test_response_size_is_bounded_at_engine_boundary():
    oversize = pdf_answer(pages=[{"page":2,"text":"X"*270000}],
        page_count=1, text="[page 2]\n"+"X"*270000,
        next_cursor=3,truncation_reason="response_bytes_limit")
    with pytest.raises(ToolHandlerError):
        _pc_chunk_projection(oversize,page=2,page_count=2)
