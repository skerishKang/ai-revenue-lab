"""Chat -> ticket -> real COM2 app -> file_id -> Chat context, all offline."""
import asyncio
import base64
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys

import httpx
import pytest

from app.auth import SESSION_COOKIE, create_session_token
from app.config import Settings, ConfigError
from app.file_lane import FileLaneClient
from app.history import UserProfile
from app.main import create_app
from app.request_contract import _validate_payload_async
from app.attachments import AttachmentValidationError
from app.claw_attachment_context import parse_claw_turn_attachments_async

SECRET = "offline-file-lane-contract-000000000000000000"
USER = "usr_" + "a" * 32
OTHER = "usr_" + "b" * 32


class History:
    async def get_user(self, user):
        return UserProfile(user, "offline@example.test", "Offline", "") if user in {USER, OTHER} else None
    async def append_exchange(self, *args, **kwargs):
        return "chat_" + "c" * 32
    async def list_conversations(self, *args, **kwargs):
        return []


def config(**kwargs):
    return Settings.from_values(auth_mode="google", public_base_url="https://chat.example.test",
        google_client_id="offline.apps.googleusercontent.com", google_client_secret="offline",
        session_secret="offline-chat-session-secret-00000000000000000", **kwargs)


def cookies(settings, user=USER):
    return {SESSION_COOKIE: create_session_token(settings, user)}


@pytest.fixture
def file_app(tmp_path, monkeypatch):
    # Cross-app fixture imports source only: Chat production has no COM2 package
    # dependency and never imports its disk/parser implementation.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "padiem-file-lane/src"))
    from padiem_file_lane.app import create_app as create_file_app
    return create_file_app(root=tmp_path, secret=SECRET)


@pytest.mark.asyncio
async def test_ticket_upload_reference_completion_and_claw_context(file_app):
    settings = config()
    lane = FileLaneClient("https://files.example.test", SECRET, transport=httpx.ASGITransport(app=file_app))
    app = create_app(settings, history_store=History(), file_lane_client=lane)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test", cookies=cookies(settings)) as chat:
        cap = await chat.get("/api/files/capabilities")
        assert cap.json()["ready"] is True
        ticket = await chat.post("/api/files/ticket", json={"size_bytes": 100}, headers={"Origin": "https://chat.example.test"})
        assert ticket.status_code == 200 and ticket.headers["cache-control"] == "no-store"
        issued = ticket.json()
        assert SECRET not in ticket.text and USER not in ticket.text  # claims encoded, never secret
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=file_app), base_url="https://files.example.test") as files:
            uploaded = await files.post("/files?filename=notes.txt", headers=issued["headers"], content=b"COM2 document context")
        assert uploaded.status_code == 201
        ref = {"type": "file", "file_id": uploaded.json()["file_id"]}
        response = await chat.post("/api/chat", json={"messages": [{"role":"user", "content":"문서를 요약해줘"}], "attachments": [ref]}, headers={"Origin":"https://chat.example.test"})
        assert response.status_code == 200
        attachment = response.json()["attachments"][0]
        assert attachment["file_id"] == ref["file_id"] and attachment["sha256"] == hashlib.sha256(b"COM2 document context").hexdigest()
        assert "COM2 document context" not in json.dumps(attachment)
        # The same shared async resolver supplies Claw's untrusted context.
        async def resolve(item):
            return await lane.resolve(USER, item)
        context, images = await parse_claw_turn_attachments_async([ref], file_resolver=resolve)
        assert "COM2 document context" in context and "신뢰되지 않은" in context and not images
        with pytest.raises(AttachmentValidationError):
            await lane.resolve(OTHER, ref)
        chat.cookies.clear()
        assert (await chat.post("/api/files/ticket", json={"size_bytes":100})).status_code == 401
        assert (await chat.post("/api/chat", json={"messages":[{"role":"user","content":"읽어줘"}],"attachments":[ref]})).status_code == 422


@pytest.mark.asyncio
async def test_no_csrf_bypass_and_no_browser_selected_owner_or_origin(file_app):
    settings = config()
    app = create_app(settings, history_store=History(), file_lane_client=FileLaneClient("https://files.example.test", SECRET, transport=httpx.ASGITransport(app=file_app)))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test", cookies=cookies(settings)) as client:
        assert (await client.post("/api/files/ticket", json={"size_bytes":1}, headers={"Origin":"https://foreign.example.test"})).status_code == 403
        for extra in [{"user_id":OTHER}, {"origin":"https://foreign.example.test"}, {"max_bytes":999}]:
            response = await client.post("/api/files/ticket", json={"size_bytes":1, **extra}, headers={"Origin":"https://chat.example.test"})
            assert response.status_code == 422
        ticket = (await client.post("/api/files/ticket", json={"size_bytes":1}, headers={"Origin":"https://chat.example.test"})).json()
        headers = ticket["headers"]
        raw = base64.urlsafe_b64decode(headers["X-Padiem-File-Ticket"] + "=" * (-len(headers["X-Padiem-File-Ticket"]) % 4))
        claims = json.loads(raw)
        assert claims["user_id"] == USER and claims["max_bytes"] == 1
        assert hmac.compare_digest(headers["X-Padiem-File-Proof"], hmac.new(SECRET.encode(), headers["X-Padiem-File-Time"].encode()+b"."+raw, hashlib.sha256).hexdigest())


@pytest.mark.asyncio
async def test_unconfigured_lane_preserves_inline_attachments_and_no_external_call():
    settings = config()
    app = create_app(settings, history_store=History())
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test", cookies=cookies(settings)) as client:
        assert (await client.get("/api/files/capabilities")).json()["ready"] is False
        assert (await client.post("/api/files/ticket", json={"size_bytes": 10_000_000}, headers={"Origin":"https://chat.example.test"})).status_code == 503
    parsed = await _validate_payload_async({"messages":[{"role":"user","content":"읽어줘"}],"attachments":[{"type":"document","name":"notes.txt","media_type":"text/plain","text":"inline stays"}]})
    assert parsed[3][0].text == "inline stays"


@pytest.mark.parametrize("origin", ["http://files.example.test", "https://u:p@files.example.test", "https://files.example.test/path", "https://files.example.test?x=y"])
def test_configured_origin_is_https_fixed_root_only(origin):
    with pytest.raises(ConfigError):
        config(file_lane_origin=origin)


@pytest.mark.asyncio
@pytest.mark.parametrize("item", [{"type":"file","file_id":"../escape"}, {"type":"file","file_id":"file_"+"a"*32,"url":"https://foreign.example"}])
async def test_reference_cannot_select_paths_or_origins(item):
    with pytest.raises(AttachmentValidationError):
        await FileLaneClient("https://files.example.test", SECRET).resolve(USER,item)


def test_browser_file_lane_routing_and_raw_file_upload():
    static = Path(__file__).resolve().parents[1] / "static"
    source = (static / "file-lane.js").read_text(encoding="utf-8")
    script = 'global.window=globalThis;\n' + source + r'''
const assert = require("node:assert/strict");
(async()=>{
  const api = PadiemFileLane;
  assert.equal(api.shouldUse({name:"large.pdf",size:9_999_999}),false);
  assert.equal(api.shouldUse({name:"large.pdf",size:10_000_000}),true);
  for(const name of ["large.txt","large.md","large.csv"]) assert.equal(api.shouldUse({name,size:10_000_000}),true);
  assert.equal(api.shouldUse({name:"photo.png",size:10_000_000}),false);
  window.PadiemAttachmentCapabilities={binarySupported:false,fileLaneSupported:true};
  for(const ext of ["pdf","docx","pptx","xlsx"]) {
    const file={name:"small."+ext,size:100};
    assert.equal(api.shouldUse(file),true);
    assert.equal(api.isBinary(file),true);
    assert.equal(api.pending(file).fileLane,true);
  }
  window.PadiemAttachmentCapabilities.fileLaneSupported=false;
  for(const ext of ["pdf","docx","pptx","xlsx"])
    assert.equal(api.shouldUse({name:"small."+ext,size:100}),false);
  let calls=[];
  const file={name:"large.pdf",size:10_000_000};
  global.fetch=async(url,options)=>{
    calls.push({url,options});
    if(url==="/api/files/capabilities") return {ok:true,json:async()=>({ready:false})};
    if(url==="/api/files/ticket") return {ok:true,json:async()=>({ok:true,upload_url:"https://files.example.test/files",headers:{"X-Padiem-File-Proof":"fixture"}})};
    return {ok:true,json:async()=>({ok:true,file_id:"file_"+"a".repeat(32),size_bytes:file.size})};
  };
  assert.equal(await api.available(),false);
  const pending=api.pending(file);
  assert.equal(pending.file,file);
  const result=await api.upload(file,new AbortController().signal);
  assert.equal(result.fileId,"file_"+"a".repeat(32));
  assert.equal(calls[2].options.body,file); // no FileReader/arrayBuffer/base64
  assert.equal(calls[2].options.credentials,"include");
  assert.equal(calls[1].options.body,JSON.stringify({size_bytes:10_000_000}));
  global.fetch=async()=>({ok:false,json:async()=>({ok:false,error:{code:"invalid_request",message:"SECRET stack trace"}})});
  await assert.rejects(api.upload(file), error =>
    error.message === "첨부할 파일을 확인한 뒤 다시 시도해 주세요." &&
    error.code === "invalid_request" && !error.message.includes("SECRET"));
  global.fetch=async()=>({ok:false,json:async()=>({ok:false,error:{code:"unexpected_failure",message:"SECRET stack trace"}})});
  await assert.rejects(api.upload(file), error =>
    error.message === "파일 업로드를 준비하지 못했습니다. 다시 시도해 주세요." &&
    error.code === "unexpected_failure" && !error.message.includes("SECRET"));
  console.log("PASS");
})().catch(e=>{console.error(e);process.exit(1)});
'''
    result = subprocess.run(["node", "-e", script], text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    app = (static / "app.js").read_text()
    assert 'if (attachment.fileId) return [{ type: "file", file_id: attachment.fileId }];' in app
    # #6579 3단계 adds a progress callback after the signal; the guarded
    # contract (the same lane upload, same abort signal) is unchanged.
    assert 'await window.PadiemFileLane.upload(attachment.file, controller.signal,' in app


def test_worker_config_never_borrows_a_process_secret(monkeypatch):
    from app.worker_config import settings_from_worker_bindings
    monkeypatch.setenv("PADIEM_CHAT_FILE_LANE_TICKET_SECRET", SECRET)
    bound = settings_from_worker_bindings({"PADIEM_CHAT_FILE_LANE_ORIGIN":"https://files.example.test"})
    assert bound.file_lane_origin == "https://files.example.test" and bound.file_lane_ticket_secret is None
    assert SECRET not in repr(config(file_lane_origin="https://files.example.test", file_lane_ticket_secret=SECRET))
    worker = (Path(__file__).resolve().parents[1] / "worker.py").read_text()
    assert 'self.env, "PADIEM_CHAT_FILE_LANE_TICKET_SECRET"' in worker


def test_picker_exposes_com2_binary_formats_when_old_binary_parser_is_missing():
    static = Path(__file__).resolve().parents[1] / "static"
    script = "global.window=globalThis;\n" + (static/"attachment-capabilities.js").read_text() + r"""
const assert=require('node:assert/strict');
const caps=PadiemAttachmentCapabilities;
caps.setBinarySupport(false);
assert(!caps.accept.includes('.pdf'));
caps.setFileLaneSupport(true);
assert(caps.accept.includes('.pdf'));
for (const ext of ['.pdf','.docx','.pptx','.xlsx']) assert(caps.accept.includes(ext));
assert(caps.copy('ko').documentFormats.includes('PDF'));
caps.setFileLaneSupport(false);
assert(!caps.accept.includes('.pdf'));
"""
    result=subprocess.run(["node","-e",script],capture_output=True,text=True)
    assert result.returncode==0,result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["pdf", "docx", "pptx", "xlsx"])
async def test_binary_reference_uses_file_lane_and_is_owner_scoped(file_app, monkeypatch, kind):
    from padiem_file_lane import parsing
    # The transport and owner checks are real. The parser is isolated here;
    # format-specific parsing is tested in the COM2 parser suite.
    monkeypatch.setattr(parsing, "parse_text", lambda path, actual: "parsed by COM2")
    lane = FileLaneClient("https://files.example.test", SECRET, transport=httpx.ASGITransport(app=file_app))
    settings = config()
    app = create_app(settings, history_store=History(), file_lane_client=lane)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test", cookies=cookies(settings)) as chat:
        cap = (await chat.get("/api/files/capabilities")).json()
        assert cap["ready"] and kind in cap["formats"]
        ticket = (await chat.post("/api/files/ticket", json={"size_bytes":20}, headers={"Origin":"https://chat.example.test"})).json()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=file_app), base_url="https://files.example.test") as files:
            uploaded = await files.post("/files?filename=sample."+kind, headers=ticket["headers"], content=(b"%PDF-1.4" if kind == "pdf" else b"fixture"))
        assert uploaded.status_code == 201
        ref = {"type":"file", "file_id":uploaded.json()["file_id"]}
        parsed = await lane.resolve(USER, ref)
        assert parsed.text == "parsed by COM2"
        assert parsed.media_type == __import__("app.file_lane", fromlist=["KINDS"]).KINDS[kind]
        with pytest.raises(AttachmentValidationError):
            await lane.resolve(OTHER, ref)

@pytest.mark.asyncio
async def test_health_requires_configured_lane_and_all_four_formats(monkeypatch):
    from app import file_lane
    for origin, secret, expected in [(None, None, False), ("https://files.example.test", None, False),
                                     ("https://files.example.test", SECRET, True)]:
        lane = FileLaneClient(origin, secret)
        app = create_app(config(), history_store=History(), file_lane_client=lane)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as chat:
            assert (await chat.get("/health")).json()["binary_document_attachment_ready"] is expected
    monkeypatch.delitem(file_lane.KINDS, "xlsx")
    lane = FileLaneClient("https://files.example.test", SECRET)
    app = create_app(config(), history_store=History(), file_lane_client=lane)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test") as chat:
        assert (await chat.get("/health")).json()["binary_document_attachment_ready"] is False



@pytest.mark.asyncio
async def test_hwpx_upload_real_lane_extraction_reaches_chat_context(file_app, monkeypatch):
    from padiem_ai_core.hwpx_package_serializer import (
        HwpxPackageContent, HwpxPackageSection, serialize_hwpx_package,
    )
    from app.documents import build_document_context

    payload = serialize_hwpx_package(HwpxPackageContent(
        sections=(HwpxPackageSection(paragraphs=("HWPX synthetic context 261101",)),)
    ))
    settings = config()
    lane = FileLaneClient("https://files.example.test", SECRET, transport=httpx.ASGITransport(app=file_app))
    app = create_app(settings, history_store=History(), file_lane_client=lane)
    from app.b14_client import B14Client
    observed = []
    async def fake_model(self, messages, **kwargs):
        observed.append(kwargs.get("additional_system_context"))
        return {"answer": "synthetic answer from document"}
    monkeypatch.setattr(B14Client, "complete", fake_model)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://chat.example.test",
                                 cookies=cookies(settings), headers={"Origin":"https://chat.example.test"}) as chat:
        caps = (await chat.get("/api/files/capabilities")).json()
        assert "hwpx" in caps["formats"]
        ticket = (await chat.post("/api/files/ticket", json={"size_bytes": len(payload)})).json()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=file_app),
                                     base_url="https://files.example.test") as files:
            upload = await files.post("/files?filename=sample.hwpx", headers=ticket["headers"], content=payload)
        assert upload.status_code == 201, upload.text
        ref = {"type":"file", "file_id":upload.json()["file_id"]}
        document = await lane.resolve(USER, ref)
        assert document.media_type == "application/hwp+zip"
        assert "HWPX synthetic context 261101" in document.text
        assert "HWPX synthetic context 261101" in build_document_context(document)
        response = await chat.post("/api/chat", json={"messages":[{"role":"user","content":"Summarize"}],
                                                       "attachments":[ref]})
        assert response.status_code == 200, response.text
        assert response.json()["attachments"][0]["file_id"] == ref["file_id"]
        assert response.json()["answer"] == "synthetic answer from document"
        assert observed and "HWPX synthetic context 261101" in observed[0]
        # The normal Chat composer deliberately sends attachments to /api/chat.
        source = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(encoding="utf-8")
        assert "if (attachments && !clawGeneralRequest)" in source
        assert "requestCompletedAnswer(article, payload" in source
        with pytest.raises(AttachmentValidationError):
            await lane.resolve(OTHER, ref)


def test_hwpx_picker_and_lane_are_consistent():
    static = Path(__file__).resolve().parents[1] / "static"
    script = "global.window=globalThis;\n" + (static / "attachment-capabilities.js").read_text(encoding="utf-8") + (
        static / "file-lane.js").read_text(encoding="utf-8") + r"""
const assert = require('node:assert/strict');
PadiemAttachmentCapabilities.setFileLaneSupport(true);
assert(PadiemAttachmentCapabilities.accept.includes('.hwpx'));
assert(PadiemFileLane.shouldUse({name:'sample.hwpx', size:100}));
assert.equal(PadiemFileLane.pending({name:'sample.hwpx', size:100}).mediaType, 'application/hwp+zip');
"""
    result = subprocess.run(["node","-e",script], text=True, capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr



@pytest.mark.asyncio
async def test_hwpx_without_readable_text_explains_the_limitation(file_app):
    from io import BytesIO
    from zipfile import ZipFile

    contents = BytesIO()
    with ZipFile(contents, "w") as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        archive.writestr("Contents/section0.xml", '<sec><p><run><pic /></run></p></sec>')
    data = contents.getvalue()
    lane = FileLaneClient("https://files.example.test", SECRET, transport=httpx.ASGITransport(app=file_app))
    headers = lane.upload_ticket(USER, len(data))["headers"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=file_app),
                                 base_url="https://files.example.test") as files:
        response = await files.post("/files?filename=image.hwpx", headers=headers, content=data)
    assert response.status_code == 201
    ref = {"type":"file", "file_id":response.json()["file_id"]}
    with pytest.raises(AttachmentValidationError) as error:
        await lane.resolve(USER, ref)
    assert str(error.value) == "HWPX 파일에서 읽을 글자를 찾지 못했습니다. 이미지나 표는 일부 읽지 못할 수 있습니다."
