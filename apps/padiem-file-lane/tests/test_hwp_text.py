"""#5895 — the lane's legacy .hwp reader: real bytes in, plain words out.

The owner's old 한글 documents arrive as OLE2 binary; this lane is the only
place they are opened (the Chat Worker ferries bytes and imports no parser), and
olefile (BSD) is the only library. Pinned here:

* the committed real sample opens into its own words — no mojibake, no refusal;
* the route answers ``{ok, text, chars}`` and maps the reader's refusals to
  their codes: an encrypted or 배포용 document never opens, the older 한글97
  layout is refused, and a file that is not HWP is refused;
* both record-header layouts walk — the standard 22-bit size and the top
  12-bit size the government writer family uses — with inline object controls
  and bare placeholders handled so the words survive them.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from padiem_file_lane import hwp_text
from padiem_file_lane.app import create_app

from test_file_lane import SECRET, ticket

FIXTURE = Path(__file__).parent / "fixtures" / "example.hwp"


@pytest.fixture(scope="module")
def sample() -> bytes:
    return FIXTURE.read_bytes()


def _client(tmp_path) -> TestClient:
    return TestClient(create_app(root=tmp_path, secret=SECRET))


# ── the real sample ────────────────────────────────────────────────────────

def test_the_real_sample_opens_into_its_own_words(sample: bytes) -> None:
    text = hwp_text.extract_text(sample)
    assert text.startswith("HWP test file")
    assert "Purpose: Provide example of this file type" in text
    assert "John Doe" in text
    assert "\ufffd" not in text
    assert len(text) > 1000


def test_the_route_hands_the_words_back_with_a_ticket(tmp_path, sample: bytes) -> None:
    response = _client(tmp_path).post("/files/hwp-text", content=sample, headers=ticket())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["text"].startswith("HWP test file")
    assert body["chars"] == len(body["text"])


def test_the_route_refuses_without_a_ticket(tmp_path, sample: bytes) -> None:
    response = _client(tmp_path).post("/files/hwp-text", content=sample)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_ticket"


# ── the flags: sealed documents never open ─────────────────────────────────

def _padded(flags_word: int, version_word: int = 0x0501) -> bytes:
    """The padded-signature FileHeader one real writer family uses."""

    header = b"HWP Document File" + b"\x00" * 15
    return (header + flags_word.to_bytes(2, "little")
            + version_word.to_bytes(2, "little") + b"\x00" * 220)


def _standard(version: str, flags: int) -> bytes:
    """The standard signature ("HWP Document File V1.30 ...") with a DWORD of flags."""

    signature = ("HWP Document File " + version).encode("ascii")
    return signature.ljust(32, b"\x00") + flags.to_bytes(4, "little") + b"\x00" * 220


class _Stream:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self, count: int = -1) -> bytes:
        return self._data if count is None or count < 0 else self._data[:count]


class _FakeOle:
    """Just enough of the olefile surface the reader touches."""

    def __init__(self, header: bytes, sections: dict[str, bytes]) -> None:
        self._header = header
        self._sections = sections

    def exists(self, name: str) -> bool:
        return name == "FileHeader"

    def openstream(self, path):
        if path == "FileHeader":
            return _Stream(self._header)
        if isinstance(path, list) and len(path) == 2 and path[0] == "BodyText":
            return _Stream(self._sections[path[1]])
        raise FileNotFoundError(path)

    def listdir(self):
        return [["BodyText", name] for name in self._sections]

    def close(self) -> None:
        pass


def _with(monkeypatch, header: bytes, section: bytes):
    book = _FakeOle(header, {"Section0": section})
    monkeypatch.setattr(hwp_text, "_ole", lambda payload: book)
    return book


def _record(tag: int, body: bytes, width: int) -> bytes:
    header = tag | (len(body) << (32 - width))
    return header.to_bytes(4, "little") + body


def _paragraph(marker: int, control_id: bytes, words: str, width: int) -> bytes:
    """One PARA_TEXT body: an inline control, words, a 표 pair, a bare marker."""

    control = marker.to_bytes(2, "little") + control_id + b"\x00" * 8
    text = words.encode("utf-16-le") + b"\r\x00"
    table = b"\x0b\x00" + b" lbt" + b"\x00" * 8 + b"\x0b\x00"
    bare = b"\x02\x00"
    return _record(66, b"\x00" * 24, width) + _record(
        hwp_text.PARA_TEXT_TAG, control + text + table + bare, width)


def test_an_encrypted_document_is_refused(sample: bytes, monkeypatch) -> None:
    import io
    import olefile

    book = olefile.OleFileIO(io.BytesIO(sample))
    header = bytearray(book.openstream("FileHeader").read(36))
    sections = {name[-1]: book.openstream(["BodyText", name[-1]]).read()
                for name in book.listdir() if len(name) == 2 and name[0] == "BodyText"}
    book.close()
    low = int.from_bytes(bytes(header[32:34]), "little") | 0x10
    header[32:34] = low.to_bytes(2, "little")
    _with(monkeypatch, bytes(header), sections["Section0"])
    with pytest.raises(hwp_text.HwpError) as refusal:
        hwp_text.extract_text(sample)
    assert refusal.value.code == "hwp_encrypted"


def test_a_distributed_document_is_refused(monkeypatch) -> None:
    section = _paragraph(0x0002, b"dces", "본문", 22)
    _with(monkeypatch, _standard("V1.30", 0x02), section)
    with pytest.raises(hwp_text.HwpError) as refusal:
        hwp_text.extract_text(b"payload")
    assert refusal.value.code == "hwp_distributable"


def test_an_older_hangul_layout_is_refused(monkeypatch) -> None:
    _with(monkeypatch, _standard("V1.21", 0x00), _paragraph(0x0002, b"dces", "본문", 22))
    with pytest.raises(hwp_text.HwpError) as refusal:
        hwp_text.extract_text(b"payload")
    assert refusal.value.code == "hwp_version_unsupported"


def test_a_file_that_is_not_hwp_is_refused(sample: bytes) -> None:
    with pytest.raises(hwp_text.HwpError) as refusal:
        hwp_text.extract_text(b"PK\x03\x04 not an ole2 file")
    assert refusal.value.code == "hwp_unreadable"


def test_the_route_maps_a_sealed_document_to_its_code(tmp_path, sample: bytes,
                                                      monkeypatch) -> None:
    import io
    import olefile

    book = olefile.OleFileIO(io.BytesIO(sample))
    header = bytearray(book.openstream("FileHeader").read(36))
    sections = {name[-1]: book.openstream(["BodyText", name[-1]]).read()
                for name in book.listdir() if len(name) == 2 and name[0] == "BodyText"}
    book.close()
    low = int.from_bytes(bytes(header[32:34]), "little") | 0x10
    header[32:34] = low.to_bytes(2, "little")
    _with(monkeypatch, bytes(header), sections["Section0"])
    response = _client(tmp_path).post("/files/hwp-text", content=sample, headers=ticket())
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "hwp_encrypted"


# ── both record-header layouts, controls included ──────────────────────────

@pytest.mark.parametrize("width", [22, 12])
def test_both_record_layouts_keep_the_words(monkeypatch, width: int) -> None:
    section = _paragraph(0x0002, b"dces", "표 안의 첫 셀, 둘째 셀", width)
    _with(monkeypatch, _standard("V1.30", 0x01), section)
    text = hwp_text.extract_text(b"payload")
    assert text == "표 안의 첫 셀, 둘째 셀"


def test_a_paragraph_without_words_is_not_an_error(monkeypatch) -> None:
    section = _record(66, b"\x00" * 24, 12) + _record(
        hwp_text.PARA_TEXT_TAG, b"\x0b\x00" + b" lbt" + b"\x00" * 8 + b"\x0b\x00", 12)
    _with(monkeypatch, _standard("V1.30", 0x01), section)
    with pytest.raises(hwp_text.HwpError) as refusal:
        hwp_text.extract_text(b"payload")
    assert refusal.value.code == "hwp_no_text"


def test_an_empty_lane_answer_is_a_plain_refusal(tmp_path) -> None:
    response = _client(tmp_path).post("/files/hwp-text", content=b"", headers=ticket())
    assert response.status_code == 422
    assert response.json()["error"]["code"] in {"hwp_unreadable", "hwp_no_text"}
