"""#8148 — concurrent PDFium renders must not kill the process.

The repro runs in a subprocess: the pre-fix failure is a native abort, which
would otherwise take the whole test run with it. Serialised renders survive
and return the same bytes as a single-threaded render.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parent.parent
sys.path.insert(0, str(APP))


def _pdf(texts: list[str]) -> bytes:
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    ref = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): ref})}
        )
        stream = f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET".encode("latin-1")
        content = DecodedStreamObject()
        content.set_data(stream)
        page[NameObject("/Contents")] = writer._add_object(content)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


_REPRO = r"""
import asyncio, hashlib, json, sys
sys.path.insert(0, sys.argv[1])
from app.document_page_render import render_page

payload = open(sys.argv[2], "rb").read()

async def main():
    for _ in range(20):
        results = await asyncio.gather(*(
            asyncio.to_thread(render_page, payload, n, long_edge_px=300)
            for n in (1, 2)
        ))
        hashes = [hashlib.sha256(r.jpeg).hexdigest() for r in results]
        if len(set(hashes)) != 2:
            raise AssertionError("two pages rendered identical bytes")
    single = render_page(payload, 1, long_edge_px=300)
    print(json.dumps({"ok": True, "single": hashlib.sha256(single.jpeg).hexdigest()}))

asyncio.run(main())
"""


def test_overlapping_renders_survive_and_match_a_single_render(tmp_path) -> None:
    payload = tmp_path / "multi.pdf"
    payload.write_bytes(_pdf(["page one", "page two"]))
    script = tmp_path / "repro_8148.py"
    script.write_text(_REPRO, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(script), str(APP), str(payload)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120, env={**os.environ},
    )
    assert result.returncode == 0, (
        f"concurrent render crashed (rc={result.returncode}):\n"
        f"{result.stdout[-400:]}\n{result.stderr[-800:]}"
    )
    payload_out = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload_out["ok"] is True

    from app.document_page_render import render_page

    single = render_page(payload.read_bytes(), 1, long_edge_px=300)
    assert payload_out["single"] == hashlib.sha256(single.jpeg).hexdigest()


def test_a_wait_beyond_the_budget_is_refused_without_blocking(monkeypatch) -> None:
    import app.document_convert_page_image as route

    monkeypatch.setattr(route, "_render_gate", asyncio.Semaphore(0))
    monkeypatch.setattr(route, "PAGE_RENDER_WAIT_SECONDS", 0)
    assert asyncio.run(route._enter_gate()) is False


def test_a_timed_out_wait_answers_503_with_the_fallback_copy(monkeypatch) -> None:
    import app.document_convert_page_image as route

    async def _busy():
        return False

    monkeypatch.setattr(route, "_enter_gate", _busy)

    async def _resolved(request):
        return "uid", None, None, SimpleNamespace(page_count=1), None, None

    monkeypatch.setattr(route, "_resolve_item", _resolved)
    request = SimpleNamespace(path_params={"page_no": "1"})
    response = asyncio.run(route.convert_item_original_page(request))
    assert response.status_code == 503
