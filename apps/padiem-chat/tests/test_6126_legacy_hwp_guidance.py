"""#6126 — the legacy-HWP guidance reaches every screen through one code.

The Chat Worker's side of decision #6126 (2026-11-01): an OLE2 ``.hwp`` picked
on a PC is refused with the single ``legacy_hwp_unsupported`` reason code —
the #2824 reason-code lane — and the wording authority is
``guidance_for_reason_code``, so the composer note, the project panel and the
council menu can never grow three different sentences. A mislabeled ``.hwp``
whose bytes are a real HWPX (ZIP) package keeps being read as HWPX.
"""
from __future__ import annotations

import sys
import zipfile
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import app.pc_file_exchange_routes as exchange                      # noqa: E402
import test_5895_pc_file_exchange as pc                             # noqa: E402
from app.binary_documents import guidance_for_reason_code           # noqa: E402

OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _hwpx_zip(*paragraphs: str) -> bytes:
    body = "".join(
        f"<hp:p><hp:runs><hp:t>{text}</hp:t></hp:runs></hp:p>" for text in paragraphs
    )
    section = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<hs:sec xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section" '
        'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">'
        f"{body}</hs:sec>"
    ).encode("utf-8")
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mimetype", b"application/hwp+zip")
        archive.writestr("Contents/section1.xml", section)
    return output.getvalue()


def test_the_guidance_wording_is_single_sourced() -> None:
    message = guidance_for_reason_code("legacy_hwp_unsupported", "application/hwp+zip")
    assert message == "한글에서 ‘다른 이름으로 저장 → HWPX’로 저장한 뒤 다시 올려 주세요."
    # The same sentence whatever the caller knows about the media type; the
    # code never maps to None (which would become a generic error on screen).
    assert guidance_for_reason_code("legacy_hwp_unsupported", None) == message


def test_a_picked_legacy_hwp_is_refused_locally_with_the_guidance_code(monkeypatch):
    import httpx

    seen = []

    def lane(request):
        seen.append(request)
        return httpx.Response(
            200, json={"ok": True, "text": "변환되어서는 안 되는 본문", "chars": 12}
        )

    dispatch = "dsp_" + "a" * 32
    state, _captured, _link, _ = pc._state(monkeypatch)
    state.file_lane_client = pc._lane_client(httpx.MockTransport(lane))
    pc._finished(state, dispatch_id=dispatch, kind="read", text=pc._hwp_fixture())
    state.history_store.dispatches[dispatch]["file_path"] = "C:/Users/qa/작년 축사.hwp"

    status, body = pc._answer(pc.pairing.run(exchange.pc_file_exchange_reference(
        pc._Request(state, body={"file_id": dispatch})
    )))

    assert status == 422 and body["error"]["code"] == "legacy_hwp_unsupported", body
    # The refusal is local: zero lane requests, the owner's bytes stay here.
    assert seen == []


def test_a_mislabeled_hwpx_named_hwp_is_read_as_hwpx(monkeypatch):
    dispatch = "dsp_" + "b" * 32
    state, _captured, _link, _ = pc._state(monkeypatch)
    pc._finished(state, dispatch_id=dispatch, kind="read", text=_hwpx_zip("HWPX로 저장한 본문"))
    state.history_store.dispatches[dispatch]["file_path"] = "C:/Users/qa/보고서.hwp"

    status, body = pc._answer(pc.pairing.run(exchange.pc_file_exchange_reference(
        pc._Request(state, body={"file_id": dispatch})
    )))

    assert status == 200 and body["ok"] is True, body
    assert body["name"] == "보고서.hwp"
    assert "HWPX로 저장한 본문" in body["text"]


def test_a_hwp_that_is_neither_ole_nor_zip_stays_unreadable(monkeypatch):
    dispatch = "dsp_" + "c" * 32
    state, _captured, _link, _ = pc._state(monkeypatch)
    pc._finished(state, dispatch_id=dispatch, kind="read",
                 text=b"\xff\x00\xfe not an ole2 or zip payload")
    state.history_store.dispatches[dispatch]["file_path"] = "C:/Users/qa/계약서.hwp"

    status, body = pc._answer(pc.pairing.run(exchange.pc_file_exchange_reference(
        pc._Request(state, body={"file_id": dispatch})
    )))

    assert status == 422 and body["error"]["code"] == "pc_reference_unreadable", body
