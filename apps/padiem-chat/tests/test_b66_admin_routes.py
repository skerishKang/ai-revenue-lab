"""Authenticated HTTP regression for B66 admin endpoints (SQLite fake D1)."""
import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from app.auth import create_session_token
from app.config import Settings
from app.b66_quote_routes import b66_quote_models, b66_quote_interpret
from app.b66_admin_routes import b66_admin_member_detail
from app.b66_admin_routes import (
    b66_admin_me, b66_admin_members, b66_admin_member_access,
    b66_admin_model_policy, b66_admin_dispatch_alerts,
)

from test_b66_admin_membership import seed_db


class FakeResolver:
    async def list_selectable_models(self):
        return [
            {"model_id":"google/gemini-3.5-flash-lite", "name":"Gemini 3.5 Flash Lite"},
            {"model_id":"deepseek/deepseek-chat", "name":"DeepSeek Chat"},
        ]


def tiny_admin_app(store, *, enforcement=False):
    settings=Settings(auth_mode="hybrid",session_secret="x"*48)
    app=Starlette(routes=[
        Route("/api/b66/quote/models",b66_quote_models,methods=["GET"]),
        Route("/api/b66/quote/interpret",b66_quote_interpret,methods=["POST"]),
        Route("/api/b66/admin/me",b66_admin_me,methods=["GET"]),
        Route("/api/b66/admin/members",b66_admin_members,methods=["GET"]),
        Route("/api/b66/admin/members/{user_id}",b66_admin_member_access,methods=["PATCH"]),
        Route("/api/b66/admin/members/{user_id}/detail",b66_admin_member_detail,methods=["GET"]),
        Route("/api/b66/admin/model-policy",b66_admin_model_policy,methods=["GET","PUT"]),
        Route("/api/b66/admin/alerts/dispatch",b66_admin_dispatch_alerts,methods=["POST"]),
    ])
    app.state.settings=settings
    app.state.history_store=object()  # B66 auth_ready requires an initialized auth store
    app.state.b66_member_admin_store=store
    app.state.b66_quote_model_resolver=FakeResolver()
    app.state.b66_membership_enforced=enforcement
    app.state.b66_signup_notifier=None
    return app,settings


@pytest.mark.asyncio
async def test_http_admin_authority_and_model_policy_rollout_guard():
    from app.b66_member_admin import D1B66MemberAdminStore
    db, admin, legacy, password_impostor = seed_db()
    app,settings=tiny_admin_app(D1B66MemberAdminStore(db, admin_email="admin@example.test"))
    def token(uid):
        return {"padiem_session":create_session_token(settings,uid)}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="https://chat.padiem.net") as client:
        anonymous=await client.get("/api/b66/admin/me")
        assert anonymous.json()=={"ok":True,"admin":False}
        denied=await client.get("/api/b66/admin/members")
        assert denied.status_code==401
        denied=await client.get("/api/b66/admin/members",cookies=token(password_impostor))
        assert denied.status_code==403
        spoof=await client.patch("/api/b66/admin/members/"+legacy,cookies=token(password_impostor),
                                 json={"status":"approved","tier":"MAX","expected_revision":0,
                                       "email":"admin@example.test"})
        assert spoof.status_code==403
        me=await client.get("/api/b66/admin/me",cookies=token(admin))
        assert me.json()["admin"] is True
        listed=await client.get("/api/b66/admin/members",cookies=token(admin))
        assert listed.status_code==200 and len(listed.json()["members"])==3
        filtered=await client.get("/api/b66/admin/members?q=cgi1003&tier=FREE&status=approved",cookies=token(admin))
        assert filtered.status_code==200 and filtered.json()["matched_total"]==1
        assert filtered.json()["members"][0]["user_id"]==legacy
        no_results=await client.get("/api/b66/admin/members?q=%25",cookies=token(admin))
        assert no_results.status_code==200 and no_results.json()["matched_total"]==0
        invalid=await client.get("/api/b66/admin/members?status=nope",cookies=token(admin))
        assert invalid.status_code==400
        denied_search=await client.get("/api/b66/admin/members?q=cgi1003",cookies=token(password_impostor))
        assert denied_search.status_code==403
        changes=await client.patch("/api/b66/admin/members/"+legacy,cookies=token(admin),
                          json={"status":"approved","tier":"PLUS","expected_revision":0})
        assert changes.status_code==200
        assert changes.json()["access"]["tier"]=="PLUS"
        replay=await client.patch("/api/b66/admin/members/"+legacy,cookies=token(admin),
                          json={"status":"approved","tier":"MAX","expected_revision":0})
        assert replay.status_code==409
        get_policy=await client.get("/api/b66/admin/model-policy",cookies=token(admin))
        assert get_policy.json()["enforcement_enabled"] is False
        policy={"expected_revision":0,"active":True,"tiers":{
          "FREE":["google/gemini-3.5-flash-lite","deepseek/deepseek-chat"],
          "PLUS":["google/gemini-3.5-flash-lite","deepseek/deepseek-chat"],
          "PRO":[],"MAX":[]},"disabled_models":[]}
        blocked=await client.put("/api/b66/admin/model-policy",cookies=token(admin),json=policy)
        assert blocked.status_code==409
        policy["active"]=False
        allowed=await client.put("/api/b66/admin/model-policy",cookies=token(admin),json=policy)
        assert allowed.status_code==200
        policy["expected_revision"]=1
        policy["active"]=True
        app.state.b66_membership_enforced=True
        allowed=await client.put("/api/b66/admin/model-policy",cookies=token(admin),json=policy)
        assert allowed.status_code==200
        assert allowed.json()["policy"]["active"] is True
        # Admin switches a model OFF globally while it remains checked for
        # PLUS/FREE. Both the model picker and direct inference must deny it.
        policy["expected_revision"]=2
        policy["disabled_models"]=["deepseek/deepseek-chat"]
        changed=await client.put("/api/b66/admin/model-policy",cookies=token(admin),json=policy)
        assert changed.status_code == 200, changed.text
        assert changed.json()["policy"]["disabled_models"] == ["deepseek/deepseek-chat"]
        visible=await client.get("/api/b66/quote/models",cookies=token(legacy))
        assert visible.status_code==200, visible.text
        assert [m["model_id"] for m in visible.json()["models"]] == ["google/gemini-3.5-flash-lite"]
        direct=await client.post("/api/b66/quote/interpret",cookies=token(legacy),json={
            "model_id":"deepseek/deepseek-chat","saved_skill_id":"fake-saved-skill",
            "message":"견적 만들어줘"
        })
        assert direct.status_code == 403
        assert direct.json()["error"]["code"] == "model_disabled"
        policy["expected_revision"] = 3
        policy["disabled_models"] = ["unregistered/vendor-model"]
        unknown=await client.put("/api/b66/admin/model-policy",cookies=token(admin),json=policy)
        assert unknown.status_code == 400

@pytest.mark.asyncio
async def test_member_detail_metadata_uses_authenticated_admin_not_browser_identity():
    import json
    from datetime import datetime, timezone
    from app.b66_member_admin import D1B66MemberAdminStore

    db, admin, legacy, impostor = seed_db()
    db.conn.executescript("""
      CREATE TABLE live_usage_buckets (
        subject_type TEXT, subject_key TEXT, bucket_type TEXT,
        bucket_start TEXT, request_count INTEGER, updated_at TEXT
      );
      CREATE TABLE b66_quote_history (
        id TEXT PRIMARY KEY, user_id TEXT, workspace_id TEXT, quote_no TEXT,
        issue_date TEXT, saved_skill_id TEXT, skill_fingerprint TEXT,
        snapshot_json TEXT, sender_json TEXT, created_at TEXT, updated_at TEXT
      );
    """)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    db.conn.execute("INSERT INTO live_usage_buckets VALUES (?,?,?,?,?,?)",
                    ("user", legacy, "day", now, 4, now))
    db.conn.execute("INSERT INTO live_usage_buckets VALUES (?,?,?,?,?,?)",
                    ("user", impostor, "day", now, 1000, now))
    db.conn.execute(
      "INSERT INTO b66_quote_history VALUES (?,?,?,?,?,?,?,?,?,?,?)",
      ("saved-1",legacy,"private","PRIVATE CUSTOMER NUMBER",
       "2026-10-11",None,None,'{"customer_secret":"not for admin"}',None,now,now)
    )
    store = D1B66MemberAdminStore(db,admin_email="admin@example.test")
    app,settings = tiny_admin_app(store)
    def cookie(uid):
        return {"padiem_session":create_session_token(settings,uid)}
    url="/api/b66/admin/members/"+legacy+"/detail"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="https://chat.padiem.net") as client:
        assert (await client.get(url)).status_code == 401
        assert (await client.get(url,cookies=cookie(impostor))).status_code == 403
        ok = await client.get(url,cookies=cookie(admin))
        assert ok.status_code == 200
        body = ok.json()
        assert body["member"]["user_id"] == legacy
        assert body["usage"]["today"] == 4
        assert body["usage"]["last_7_days"] == 4
        assert body["quotes"]["saved_count"] == 1
        assert body["usage"]["model_breakdown_available"] is False
        assert body["usage"]["scope"] == "padiem_chat_all_ai_requests"
        assert "PRIVATE CUSTOMER NUMBER" not in ok.text
        assert "customer_secret" not in ok.text
        assert (await client.get("/api/b66/admin/members/bad-id/detail",
                                 cookies=cookie(admin))).status_code == 404
