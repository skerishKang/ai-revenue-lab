"""Synthetic, offline format/window fixtures; no document bodies in output."""
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile
import hashlib
import json

import anyio
import pytest

from test_file_lane import client, pdf_bytes, ticket, upload
from padiem_ai_core.document_normalization import (
    DocumentNormalizationError, MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES, extract_binary_document,
)
from padiem_ai_core.pdf_markdown import convert_pdf_to_markdown
from padiem_file_lane.app import create_app
from padiem_file_lane import parsing


def package(members):
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_STORED) as archive:
        for name, body in members.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def docx(text="COM2 Word text", padding=0):
    return package({"word/document.xml": (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        + ('<!--' + 'x' * padding + '-->' if padding else '')
        + '<w:body><w:p><w:r><w:t>' + text + '</w:t></w:r></w:p></w:body></w:document>'
    ).encode()})


def pptx():
    return package({"ppt/slides/slide1.xml": b'<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>COM2 Slides text</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>'})


def xlsx():
    from openpyxl import Workbook
    workbook = Workbook()
    workbook.active['A1'] = 'COM2 Workbook text'
    buffer = BytesIO()
    workbook.save(buffer)
    workbook.close()
    return buffer.getvalue()


@pytest.mark.parametrize("kind,fixture,expected", [
    ("txt", lambda: '한글🙂\r\ntext'.encode(), '한글🙂\ntext'),
    ("md", lambda: b'# heading\n', '# heading'),
    ("csv", lambda: b'\xef\xbb\xbfcol1,col2\n1,2\n', 'col1,col2\n1,2'),
    ("pdf", pdf_bytes, 'COM2 PDF text'),
    ("docx", docx, 'COM2 Word text'),
    ("pptx", pptx, 'COM2 Slides text'),
    ("xlsx", xlsx, 'COM2 Workbook text'),
])
def test_format_upload_parse_disk_cache_and_window(client, tmp_path, monkeypatch, kind, fixture, expected):
    content = fixture()
    meta = upload(client, content, 'sample.' + kind).json()
    assert meta['kind'] == kind and meta['sha256'] == hashlib.sha256(content).hexdigest()
    url = f'/files/{meta["file_id"]}/text'
    complete = client.get(url, headers=ticket())
    assert complete.status_code == 200 and expected in complete.text
    if kind == 'pdf':
        assert complete.text == convert_pdf_to_markdown(name='file.pdf', media_type='application/pdf', payload=content).markdown
    assert len(list(tmp_path.rglob('text-v2.txt'))) == 1
    # A subsequent window must read durable output without invoking a parser.
    monkeypatch.setattr(parsing, 'parse_text', lambda *args: pytest.fail('cached result reparsed'))
    result = client.get(url, params={'offset': 1, 'max_chars': 5}, headers=ticket())
    assert result.text == complete.text[1:6]
    assert result.headers['x-file-lane-next-offset'] == str(min(6, len(complete.text)))
    assert result.headers['x-file-lane-eof'] == str(len(complete.text) <= 6).lower()
    assert client.get(url, headers=ticket(user='usr_other')).status_code == 404


def test_unicode_windows_reconstruct_large_result_without_splitting_characters(client):
    content = '가🙂éZ\n' * 20_000
    meta = upload(client, content.encode(), 'large.txt').json()
    url = f'/files/{meta["file_id"]}/text'
    first = client.get(url, params={'offset': 0}, headers=ticket())
    assert first.text == content[:64000]
    second = client.get(url, params={'offset': 64000, 'max_chars': len(content)}, headers=ticket())
    assert first.text + second.text == content
    assert second.headers['x-file-lane-eof'] == 'true'
    past = client.get(url, params={'offset': len(content) + 10, 'max_chars': 4}, headers=ticket())
    assert past.text == '' and past.headers['x-file-lane-eof'] == 'true'
    huge = client.get(url, params={'max_chars': 10 ** 30}, headers=ticket())
    assert huge.status_code == 200 and huge.text == content


@pytest.mark.parametrize('params', [{'offset': '-1'}, {'offset': 'a'}, {'max_chars': '0'}, {'max_chars': '-1'}])
def test_invalid_windows_do_not_start_parsing(client, monkeypatch, params):
    meta = upload(client).json()
    monkeypatch.setattr(parsing, 'parse_text', lambda *args: pytest.fail('invalid window parsed'))
    result = client.get(f'/files/{meta["file_id"]}/text', params=params, headers=ticket())
    assert result.status_code == 400 and result.json()['error']['code'] == 'invalid_text_window'


def test_com2_accepts_member_above_worker_budget_and_default_core_remains_bounded(client):
    payload = docx(padding=MAX_OOXML_ENTRY_UNCOMPRESSED_BYTES + 1)
    args = dict(name='sample.docx', media_type=parsing.MEDIA['docx'], payload=payload)
    with pytest.raises(DocumentNormalizationError) as failure:
        extract_binary_document(**args)
    assert failure.value.code == 'ooxml_entry_size'
    meta = upload(client, payload, 'sample.docx', ticket(maximum=len(payload))).json()
    response = client.get(f'/files/{meta["file_id"]}/text', headers=ticket())
    assert response.status_code == 200 and 'COM2 Word text' in response.text
    # Request-local None must not leak into subsequent Worker/default calls.
    with pytest.raises(DocumentNormalizationError) as failure:
        extract_binary_document(**args)
    assert failure.value.code == 'ooxml_entry_size'


@pytest.mark.parametrize('payload', [b'not a zip', docx('<!DOCTYPE forbidden>'), package({'../evil.xml': b'<xml/>'})])
def test_malformed_or_unsafe_ooxml_does_not_publish_text(client, tmp_path, payload):
    meta = upload(client, payload, 'unsafe.docx').json()
    result = client.get(f'/files/{meta["file_id"]}/text', headers=ticket())
    assert result.status_code == 422 and result.json()['error']['code'] == 'parse_failed'
    assert not list(tmp_path.rglob('text-v2.txt')) and not list(tmp_path.rglob('*.part'))


def write_100mb_pdf(path):
    """Valid native-text PDF with a 100MiB embedded file, generated on disk.

    This exercises actual bytes/storage/seekable parsing, not a fake size or a
    mocked parser. It is a large-byte fixture, not a many-page performance claim.
    """
    offsets = [0]
    size = 100 * 1024 * 1024
    with path.open('wb') as output:
        output.write(b'%PDF-1.7\n')
        def obj(number, data):
            offsets.append(output.tell())
            output.write(f'{number} 0 obj\n'.encode() + data + b'\nendobj\n')
        obj(1, b'<< /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles << /Names [(fixture.bin) 6 0 R] >> >> >>')
        obj(2, b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>')
        obj(3, b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>')
        obj(4, b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>')
        content = b'BT /F1 12 Tf 20 200 Td (Large COM2 PDF text) Tj ET'
        obj(5, f'<< /Length {len(content)} >>\nstream\n'.encode() + content + b'\nendstream')
        obj(6, b'<< /Type /Filespec /F (fixture.bin) /EF << /F 7 0 R >> >>')
        offsets.append(output.tell())
        output.write(f'7 0 obj\n<< /Type /EmbeddedFile /Length {size} >>\nstream\n'.encode())
        block = b'x' * (64 * 1024)
        for _ in range(size // len(block)):
            output.write(block)
        output.write(b'\nendstream\nendobj\n')
        xref = output.tell()
        output.write(b'xref\n0 8\n0000000000 65535 f \n')
        for offset in offsets[1:]:
            output.write(f'{offset:010d} 00000 n \n'.encode())
        output.write(f'trailer\n<< /Size 8 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())


def test_100mb_pdf_stream_upload_real_core_parse_and_window(tmp_path):
    from starlette.testclient import TestClient
    original = tmp_path / 'large.pdf'
    write_100mb_pdf(original)
    assert original.stat().st_size > 100 * 1024 * 1024
    app = create_app(root=tmp_path / 'store', secret='offline-file-lane-test-secret-000000000000')
    events, digest = [], hashlib.sha256()
    with original.open('rb') as source:
        async def receive():
            block = source.read(1024 * 1024)
            digest.update(block)
            return {'type': 'http.request', 'body': block, 'more_body': bool(block)}
        async def send(event):
            events.append(event)
        scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST',
                 'scheme': 'http', 'path': '/files', 'raw_path': b'/files', 'query_string': b'filename=large.pdf',
                 'headers': [(k.encode(), v.encode()) for k,v in ticket(maximum=original.stat().st_size).items()],
                 'server': ('localhost', 8788), 'client': ('localhost', 1234)}
        async def run():
            await app(scope, receive, send)
        anyio.run(run)
    assert events[0]['status'] == 201
    meta = json.loads(events[1]['body'])
    assert meta['size_bytes'] == original.stat().st_size and meta['sha256'] == digest.hexdigest()
    # Prove original PDF bytes are never materialized by Path.read_bytes().
    original_read = Path.read_bytes
    def read(path):
        assert path.name != 'data', 'PDF input must stay seekable on disk'
        return original_read(path)
    from unittest.mock import patch
    with patch.object(Path, 'read_bytes', read), TestClient(app) as client:
        response = client.get(f'/files/{meta["file_id"]}/text', params={'offset': 0, 'max_chars': 64000}, headers=ticket())
        assert response.status_code == 200 and 'Large COM2 PDF text' in response.text
        assert response.headers['x-file-lane-eof'] == 'true'
