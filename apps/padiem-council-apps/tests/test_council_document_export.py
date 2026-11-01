"""2026-11-01: 결과 내려받기 — 한글(HWPX)·워드(DOCX)·텍스트.

브라우저에서 바로 만든다(static/document-export.js, 서버 왕복 없음):
- HWPX 패키지 스켈레톤은 @kimdayoun/hwpx-mcp(MIT)의 것을 이식했고
  THIRD_PARTY_NOTICES.md에 표기했다. 스켈레톤은 한글 프로그램이 읽는
  OWPML(zip+XML) 구조다.
- DOCX 구조는 저장소의 kagent 문서 출력기
  (apps/korean-ai-code-agent/src/kagent/document_export.py, #2016/#2115)와
  같은 최소 WordprocessingML이다.

본 시험은 하네스가 실제 버튼 클릭으로 얻은 바이트를 풀어 구조·한글·파일명을
검증한다. 한컴오피스·워드가 없는 환경에서의 최소 계약은 (1) zip 무결성
(CRC32 포함), (2) 필수 파트 존재, (3) XML well-formed, (4) 한글 본문 포함,
(5) 기존 규칙을 따르는 파일 이름이다.
"""
from __future__ import annotations

import base64
import io
import json
import xml.etree.ElementTree as ET
import zipfile

from _council_module import run

from app.asset_versions import compute_versions

SPEECH_HWPX_MIME = b"application/hwp+zip"


def _zip_of(detail) -> zipfile.ZipFile:
    assert detail["bytes"], "the export button produced no bytes"
    raw = base64.b64decode(detail["bytes"])
    assert raw[:2] == b"PK", "the export is not a zip package"
    zf = zipfile.ZipFile(io.BytesIO(raw))
    assert zf.testzip() is None, "a stored entry fails its CRC32"
    return zf


def _well_formed(zf: zipfile.ZipFile, names) -> None:
    for name in names:
        ET.fromstring(zf.read(name))  # raises on malformed XML


def test_the_speech_download_buttons_carry_names_and_packages():
    seen = run("export")
    speech = seen["speech"]
    # 파일 이름 규칙은 지금처럼: 종류_행사명_날짜.확장자
    assert speech["hwpx"]["download"] == "축사_주민 감사의 밤_2026-11-01.hwpx"
    assert speech["docx"]["download"] == "축사_주민 감사의 밤_2026-11-01.docx"
    assert speech["txt"] == "축사_주민 감사의 밤_2026-11-01.txt"


def test_the_hwpx_package_is_a_hangul_readable_owpml_zip():
    seen = run("export")
    zf = _zip_of(seen["speech"]["hwpx"])
    # mimetype first, byte-exact — the OWPML entry contract.
    assert zf.namelist()[0] == "mimetype"
    assert zf.read("mimetype") == SPEECH_HWPX_MIME
    parts = ("version.xml", "META-INF/container.xml", "META-INF/manifest.xml",
             "settings.xml", "Contents/content.hpf", "Contents/header.xml",
             "Contents/section0.xml")
    for name in parts:
        assert name in zf.namelist(), name
    _well_formed(zf, parts)
    section = zf.read("Contents/section0.xml").decode("utf-8")
    assert "존경하는 시민 여러분" in section, "the manuscript body must survive the packaging"
    header = zf.read("Contents/header.xml").decode("utf-8")
    assert "함초롬바탕" in header
    assert header.count("<hh:charPr ") == 3 and "<hh:bold/>" in header, \
        "제목(20pt 볼드)·소제목(14pt 볼드)·본문 세 글자 모양이 필요하다"
    manifest = zf.read("Contents/content.hpf").decode("utf-8")
    for expected in ("Contents/header.xml", "Contents/section0.xml", "settings.xml"):
        assert expected in manifest


def test_the_docx_package_is_a_word_readable_ooxml_zip():
    seen = run("export")
    zf = _zip_of(seen["speech"]["docx"])
    names = zf.namelist()
    for name in ("[Content_Types].xml", "_rels/.rels", "word/document.xml"):
        assert name in names, name
    _well_formed(zf, names)
    document = zf.read("word/document.xml").decode("utf-8")
    assert "주민 감사의 밤" in document, "the event title opens the document"
    assert "존경하는 시민 여러분" in document, "the manuscript body survives"
    assert 'w:val="36"' in document and "<w:b/>" in document, "the title is large and bold"
    assert "<w:sectPr>" in document, "the page setup closes the body"
    content_types = zf.read("[Content_Types].xml").decode("utf-8")
    assert "wordprocessingml.document.main+xml" in content_types


def test_the_book_export_keeps_the_drafts_structure():
    seen = run("export")
    book = seen["book"]
    assert book["hwpx"]["download"] == "활동집 - 10월 활동집.hwpx"
    assert book["docx"]["download"] == "활동집 - 10월 활동집.docx"
    zf = _zip_of(book["hwpx"])
    section = zf.read("Contents/section0.xml").decode("utf-8")
    assert "10월 활동집" in section, "첫 줄이 문서 제목으로 간다"
    assert "기간: 2026-10-01 ~ 2026-10-31" in section, "기간 줄이 살아 있다"
    assert "제1장 주민 간담회" in section and "제2장 현장 방문" in section, "회의별 소제목"
    assert "관내 주민 40명이 참석해 정자 조성을 논의했다." in section, "본문 문단"
    assert section.count('charPrIDRef="2"') >= 2, "소제목은 큰 글자 모양을 쓴다"
    docx = _zip_of(book["docx"]).read("word/document.xml").decode("utf-8")
    assert "제1장 주민 간담회" in docx and 'w:val="28"' in docx, "소제목은 볼드 큰 글자"
    assert "관내 주민 40명이 참석해 정자 조성을 논의했다." in docx


def test_the_export_module_rides_the_same_versioned_asset_lane():
    # document-export.js is loaded dynamically, like photo-resize.js — it must
    # be in the served version map and loaded through versionedAsset().
    import re
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "static" / "council-app.js").read_text(encoding="utf-8")
    assert re.search(r'script\.src = "\./static/document-export\.js";', js)
    assert 'versionedAsset(script.src)' in js
    versions = compute_versions(Path(__file__).resolve().parents[1] / "static")
    assert "document-export.js" in versions
