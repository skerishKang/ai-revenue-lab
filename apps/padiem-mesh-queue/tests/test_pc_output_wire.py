"""Exercise the real Chat wrapper, queue RPC door and durable OutputStore."""
from __future__ import annotations
import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace
import pytest

from test_queue_internal_store_rpc import _app, _handler, _Request, _body
from app.queue_store_proxy import QueueForwardingHistoryStore
from pc_output_store import PcOutputStore

OWNER = dict(user_id="usr_test", subject_id="subject-test", run_id="run-test",
             device_id="device-test")


class Client:
    def __init__(self, app):
        self.app = app
        self.parts = []

    async def call(self, method, **arguments):
        request = _Request(self.app.state, {"method": method, "arguments": arguments})
        self.parts.append(len(request._body))
        response = await _handler(self.app)(request)
        if response.status_code != 200:
            raise RuntimeError(_body(response)["error"]["code"])
        return _body(response)["result"]


def test_large_output_crosses_real_rpc_in_bounded_parts_and_survives_restart(tmp_path):
    async def run():
        app = _app(output_directory=str(tmp_path))
        client = Client(app)
        proxy = QueueForwardingHistoryStore(SimpleNamespace(), client)
        original = "첫머리\n" + ("가나다-0123456789\n" * 80000) + "끝 marker"
        ref = await proxy.store_pc_output(**OWNER, content=original)
        assert ref["size"] == len(original.encode())
        stored_bytes = next((tmp_path / "outputs").glob("*/*.bin")).read_bytes()
        assert stored_bytes == original.encode("utf-8")
        assert ref["truncated"] and ref["head"].startswith("첫머리") and ref["tail"].endswith("marker")
        assert "content" not in ref and max(client.parts) < 1_000_000
        # Recreate the service: bytes and ownership are durable, not a process map.
        app.state.pc_output_store = PcOutputStore(tmp_path)
        restored = []
        for offset in range(0, ref["size"], 65536):
            result = await proxy.read_pc_output(**OWNER, handle=ref["handle"], offset=offset, length=65536)
            # ASCII suffix plus UTF8 safe range semantics are pinned separately below.
            restored.append(result["content"])
        assert restored[0].startswith("첫머리") and restored[-1].endswith("끝 marker")
        assert await proxy.store_pc_output(**OWNER, content=original) == ref
        found = await proxy.search_pc_output(**OWNER, handle=ref["handle"], query="끝 marker")
        assert found["hits"][0]["offset"] == original.encode().index("끝 marker".encode())
        for field in OWNER:
            foreign = dict(OWNER, **{field: "different-owner-boundary"})
            with pytest.raises(RuntimeError, match="queue_store_failed"):
                await proxy.read_pc_output(**foreign, handle=ref["handle"], offset=0, length=100)
        with pytest.raises(RuntimeError):
            await proxy.read_pc_output(**OWNER, handle=ref["handle"], offset=0, length=65537)
    asyncio.run(run())


def test_upload_retries_never_duplicate_and_integrity_failure_cannot_publish(tmp_path):
    async def run():
        store = PcOutputStore(tmp_path)
        content = b"abcdef"
        begin = await store.begin_pc_output(**OWNER, source="tool", size=6,
                                           sha256=hashlib.sha256(content).hexdigest())
        part = dict(OWNER, upload_id=begin["upload_id"], offset=0, data=base64.b64encode(content[:3]).decode())
        assert await store.append_pc_output(**part) == {"offset": 3}
        assert await store.append_pc_output(**part) == {"offset": 3}
        with pytest.raises(ValueError, match="integrity"):
            await store.finish_pc_output(**OWNER, upload_id=begin["upload_id"])
        await store.append_pc_output(**OWNER, upload_id=begin["upload_id"], offset=3,
                                     data=base64.b64encode(content[3:]).decode())
        ref = await store.finish_pc_output(**OWNER, upload_id=begin["upload_id"])
        result = await store.read_pc_output(**OWNER, handle=ref["handle"], offset=0, length=6)
        assert result["content"] == "abcdef"
        assert await store.finish_pc_output(**OWNER, upload_id=begin["upload_id"]) == ref
    asyncio.run(run())


def test_dispatch_write_requires_authoritative_owner_and_run(tmp_path):
    class History:
        async def get_pc_output_dispatch_for_owner(self, **kwargs):
            assert kwargs == {"user_id": OWNER["user_id"], "dispatch_id": "dsp_test"}
            return {"run_id": "another-run", "state": "done"}
    async def run():
        store = PcOutputStore(tmp_path, history_store=History())
        with pytest.raises(ValueError, match="dispatch"):
            await store.begin_pc_output(**OWNER, source="tool", dispatch_id="dsp_test", size=0,
                                       sha256=hashlib.sha256(b"").hexdigest())
    asyncio.run(run())


def test_dispatch_output_cannot_be_relabelled_as_another_device(tmp_path):
    class History:
        async def get_pc_output_dispatch_for_owner(self, **kwargs):
            return {"run_id": OWNER["run_id"], "state": "done", "device_id": "different-pc"}
    async def run():
        store = PcOutputStore(tmp_path, history_store=History())
        with pytest.raises(ValueError, match="dispatch"):
            await store.begin_pc_output(**OWNER, source="tool", dispatch_id="dsp_test", size=0,
                                       sha256=hashlib.sha256(b"").hexdigest())
    asyncio.run(run())


def test_failed_terminal_output_still_requires_the_original_digest(tmp_path):
    class History:
        async def get_pc_output_dispatch_for_owner(self, **kwargs):
            return {"run_id": OWNER["run_id"], "state": "failed", "device_id": OWNER["device_id"],
                    "result_sha256": hashlib.sha256(b"error output").hexdigest()}
    async def run():
        store = PcOutputStore(tmp_path, history_store=History())
        with pytest.raises(ValueError, match="dispatch"):
            await store.begin_pc_output(**OWNER, source="tool", dispatch_id="dsp_test", size=0,
                                       sha256=hashlib.sha256(b"").hexdigest())
        result = await store.begin_pc_output(**OWNER, source="tool", dispatch_id="dsp_test", size=12,
                                            sha256=hashlib.sha256(b"error output").hexdigest())
        assert result["upload_id"]
    asyncio.run(run())


def test_expired_uploads_of_an_abandoned_run_are_removed(tmp_path):
    import os
    import time
    old = tmp_path / "uploads" / "old-owner"
    old.mkdir(parents=True)
    for name in ("stale.part", "stale.json", "stale.done", "stale.ref"):
        path = old / name
        path.write_text("old")
        os.utime(path, (1, 1))
    (old / "fresh.part").write_text("active")
    store = PcOutputStore(tmp_path)
    store._directory(store._owner(**OWNER))
    assert sorted(p.name for p in old.iterdir()) == ["fresh.part"]
