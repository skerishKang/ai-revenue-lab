"""An old browser gets a refresh instruction and cannot trigger recovery."""
import json
import subprocess
from pathlib import Path

import pytest
import test_5573_pc_http_boundary as h


@pytest.mark.asyncio
async def test_real_orchestration_contract_and_other_unknowns(monkeypatch):
    app, bridge, _store = h._wire(monkeypatch)
    base = {"messages": [{"role": "user", "content": "synthetic"}],
            "tier": "free", "skill": "auto", "pc_run_id": h.PC_RUN}
    async with h._client(app) as client:
        for extra in ({"mode": "auto"}, {"country": "kr"},
                      *({"skill": x} for x in ("explain", "write", "translate",
                                                "summarize", "code", "brainstorm"))):
            response = await client.post("/api/orchestration",
                                         headers={"Origin": h.ORIGIN}, json={**base, **extra})
            assert response.status_code == 422
            assert response.json()["error"] == {
                "code": "stale_chat_client",
                "message": '\ud654\uba74\uc774 \uc624\ub798\ub418\uc5c8\uc2b5\ub2c8\ub2e4. \uc0c8\ub85c\uace0\uce68\uc774 \ud544\uc694\ud569\ub2c8\ub2e4.',
            }
        # Standalone Chat surfaces share the same request contract.
        for path in ("/api/chat", "/api/chat/stream"):
            response = await client.post(path, headers={"Origin": h.ORIGIN},
                                         json={**base, "mode": "auto"})
            assert response.status_code == 422
            assert response.json()["error"]["code"] == "stale_chat_client"
        assert bridge.requests == []
        rejected = await client.get("/api/claw/runs/" + h.PC_RUN + "/pending-result")
        assert rejected.status_code == 404
        unknown = await client.post("/api/orchestration", headers={"Origin": h.ORIGIN},
                                    json={**base, "unexpected": 1})
        assert unknown.status_code == 422
        assert unknown.json()["error"]["code"] == "invalid_request"
        accepted = await client.post("/api/orchestration", headers={"Origin": h.ORIGIN}, json=base)
        assert accepted.status_code == 200
        assert len(bridge.requests) == 1


def test_http_422_is_terminal_and_shows_refresh(tmp_path):
    transport = (Path(__file__).parents[1] / "static" / "chat-transport.js").read_text(encoding="utf-8")
    app = (Path(__file__).parents[1] / "static" / "app.js").read_text(encoding="utf-8")
    # The real outer catch suppresses recovery when transport marks a terminal refusal.
    assert "!error?.terminalRecord" in app
    js = r"""
global.window = globalThis;
let calls = [];
global.fetch = async (url) => {
  calls.push(url);
  if (url === "/api/orchestration/status")
    return {ok:true,json:async()=>({orchestration_ready:true,authenticated:true})};
  if (url === "/api/orchestration")
    return {ok:false,status:422,headers:{get:()=> "application/json"},
            json:async()=>({error:{code:"stale_chat_client"}})};
  throw new Error("unexpected fetch: "+url);
};
""" + transport + r"""
(async () => {
  try { await PadiemChatTransport.requestStreaming({}, null); throw Error("accepted"); }
  catch (error) {
    if (error.code !== "stale_chat_client" || !error.terminalRecord ||
        !error.message.includes('\uc0c8\ub85c\uace0\uce68')) throw error;
  }
  if (calls.length !== 2) throw Error("unexpected recovery");
  process.stdout.write("PASS");
})().catch(e=>{console.error(e);process.exit(1)});
"""
    script = tmp_path / "transport.js"
    script.write_text(js, encoding="utf-8")
    result = subprocess.run(["node", str(script)], capture_output=True, text=True, check=True)
    assert result.stdout == "PASS"
