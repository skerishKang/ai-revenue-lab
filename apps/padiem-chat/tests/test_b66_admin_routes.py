"""Authenticated HTTP regression for B66 admin endpoints (SQLite fake D1)."""
import httpx
import pytest
from starlette.applications import Starlette
from starlette.routing import Route

from app.auth import create_session_token
from app.config import Settings
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
        Route("/api/b66/admin/me",b66_admin_me,methods=["GET"]),
        Route("/api/b66/admin/members",b66_admin_members,methods=["GET"]),
        Route("/api/b66/admin/members/{user_id}",b66_admin_member_access,methods=["PATCH"]),
        Route("/api/b66/admin/model-policy",b66_admin_model_policy,methods=["GET","PUT"]),
        Route("/api/b66/admin/alerts/dispatch",b66_admin_dispatch_alerts,methods=["POST"]),
    ])
    app.state.settings=settings
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
          "FREE":["google/gemini-3.5-flash-lite"],"PLUS":[],"PRO":[],"MAX":[]}}
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
