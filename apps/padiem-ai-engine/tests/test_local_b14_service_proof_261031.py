"""Host B14 proof interoperates with the real B14 verification function."""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
import pytest
from app import local_runtime as rt

path = Path(__file__).resolve().parents[2] / "korean-ai-platform/app/pilot/service_proof.py"
spec = importlib.util.spec_from_file_location("_b14_service_proof_actual", path)
assert spec and spec.loader
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)

TEST_SECRET = "synthetic-proof-" + "q" * 40
STAMP = 1793433600

class Response:
    status_code = 200
    headers = {"content-type": "text/event-stream"}
    content = b"data: done\n\n"

class CapturingClient:
    def __init__(self, record): self.record = record
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    async def request(self, method, url, headers, content):
        self.record.update(method=method, url=url, headers=headers, body=content)
        return Response()

def binding(monkeypatch, values):
    record = {}
    monkeypatch.setattr(rt.time, "time", lambda: STAMP)
    monkeypatch.setattr(rt.httpx, "AsyncClient", lambda **kw: CapturingClient(record))
    return rt.LocalB14Binding("http://127.0.0.1:8789", values=values), record

@pytest.mark.parametrize("body", [
    b'{ "model":"example", "messages":[{"content":"\\uac00"}] }',
    b'{"model":"example","stream":true,"messages":[{"content":"hello"}]}',
])
async def test_real_server_verifies_exact_wire_bytes_and_rejects_tamper_and_stale(monkeypatch, body):
    b, record = binding(monkeypatch, {rt.B14_PROOF_SECRET_ENV: TEST_SECRET})
    await b.fetch(rt.LocalRequest("https://b14.internal/api/pilot/v1/chat/completions",
        method="POST", headers={"Accept":"text/event-stream", "X-Padiem-B14-Proof":"fake"}, body=body))
    assert record["body"] == body
    headers = record["headers"]
    timestamp = headers[server.PROOF_TIME_HEADER]
    proof = headers[server.PROOF_HEADER]
    assert server.verify_service_proof(TEST_SECRET, timestamp, proof, record["body"], now_seconds=STAMP)
    assert not server.verify_service_proof(TEST_SECRET, timestamp, proof, record["body"] + b" ", now_seconds=STAMP)
    assert not server.verify_service_proof(TEST_SECRET, timestamp, proof, record["body"], now_seconds=STAMP + server.MAX_PROOF_SKEW_SECONDS + 1)

async def test_missing_secret_fails_before_network_and_startup_warns(monkeypatch, caplog):
    b, record = binding(monkeypatch, {})
    with pytest.raises(rt.LocalRuntimeError, match="p01_local_b14_proof_unconfigured"):
        await b.fetch(rt.LocalRequest("https://b14.internal/test", method="POST", body=b"{}"))
    assert record == {}
    with caplog.at_level("WARNING"):
        rt._local_bindings({rt.B14_ORIGIN_ENV:"http://127.0.0.1:8789"})
    assert "p01_local_b14_proof_unconfigured" in caplog.text

async def test_named_private_file_and_environment_precedence(monkeypatch, tmp_path):
    secret = tmp_path / rt.B14_PROOF_SECRET_ENV
    secret.write_text(TEST_SECRET, encoding="utf-8")
    secret.chmod(0o600)
    b, record = binding(monkeypatch, {rt.B14_SECRET_DIR_ENV:str(tmp_path)})
    await b.fetch(rt.LocalRequest("https://b14.internal/test", method="POST", body=b"file"))
    headers = record["headers"]
    assert server.verify_service_proof(TEST_SECRET, headers[server.PROOF_TIME_HEADER], headers[server.PROOF_HEADER], b"file", now_seconds=STAMP)
    override = "synthetic-env-" + "z" * 40
    b, record = binding(monkeypatch, {rt.B14_SECRET_DIR_ENV:str(tmp_path), rt.B14_PROOF_SECRET_ENV:override})
    await b.fetch(rt.LocalRequest("https://b14.internal/test", method="POST", body=b"env"))
    headers = record["headers"]
    assert server.verify_service_proof(override, headers[server.PROOF_TIME_HEADER], headers[server.PROOF_HEADER], b"env", now_seconds=STAMP)

@pytest.mark.skipif(rt.os.name != "posix", reason="POSIX file permission check")
async def test_group_readable_file_cannot_authorize(monkeypatch, tmp_path):
    secret = tmp_path / rt.B14_PROOF_SECRET_ENV
    secret.write_text(TEST_SECRET, encoding="utf-8")
    secret.chmod(0o640)
    b, record = binding(monkeypatch, {rt.B14_SECRET_DIR_ENV:str(tmp_path)})
    with pytest.raises(rt.LocalRuntimeError, match="p01_local_b14_proof_unconfigured"):
        await b.fetch(rt.LocalRequest("https://b14.internal/test", method="POST", body=b"{}"))
    assert record == {}
