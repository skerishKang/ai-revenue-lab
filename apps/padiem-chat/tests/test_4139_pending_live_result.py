"""One accepted PC run can be read only by its owner, without redispatch."""
import asyncio
import json
from types import SimpleNamespace

from starlette.requests import Request
from app.claw_general_routes import _claw_general_sse
from app.claw_routes import claw_pending_result


def test_pc_receipt_reports_pending_instead_of_done():
    response = _claw_general_sse(
        "PC running", conversation_id="chat_abc",
        pending_run_id="run_" + "a" * 24,
    )
    body = response.body.decode("utf8")
    assert '"pc_pending":true' in body
    assert '"run_id":"run_' in body
    assert '"conversation_id":"chat_abc"' in body


def test_normal_sse_never_has_pending_run():
    response = _claw_general_sse("Completed", conversation_id="chat_abc")
    assert b"pc_pending" not in response.body


def test_pending_result_does_not_call_pc_or_list_all_runs(monkeypatch):
    import app.claw_routes as routes
    owner = "owner"
    calls = []
    class History:
        async def get_claw_run(self, user_id, run_id):
            calls.append(("run",user_id,run_id))
            return {"run_id":run_id,"conversation_id":"chat_abc","status":"completed"}
        async def get_claw_run_result_message(self,user_id,run_id,conversation_id):
            calls.append(("result",user_id,run_id))
            return "PC RESULT"
    monkeypatch.setattr(routes, "auth_ready", lambda request:True)
    monkeypatch.setattr(routes, "current_user_id", lambda request:owner)
    scope={"type":"http","method":"GET","path":"/api/claw/runs/run_abc123abc123/pending-result",
           "path_params":{"run_id":"run_abc123abc123"},"headers":[]}
    req=Request(scope)
    req.scope["app"]=SimpleNamespace(state=SimpleNamespace(history_store=History()))
    response=asyncio.run(claw_pending_result(req))
    assert response.status_code==200
    assert json.loads(response.body)["result"]["answer"]=="PC RESULT"
    assert [c[0] for c in calls]==["run","result"]


def test_pending_result_rejects_foreign_run(monkeypatch):
    import app.claw_routes as routes
    class History:
        async def get_claw_run(self,user_id,run_id):return None
    monkeypatch.setattr(routes,"auth_ready",lambda request:True)
    monkeypatch.setattr(routes,"current_user_id",lambda request:"owner")
    req=Request({"type":"http","method":"GET","path":"/api/claw/runs/run_abc123abc123/pending-result",
                 "path_params":{"run_id":"run_abc123abc123"},"headers":[]})
    req.scope["app"]=SimpleNamespace(state=SimpleNamespace(history_store=History()))
    result=asyncio.run(claw_pending_result(req))
    assert result.status_code==404
