"""Account comparison uses existing authentication and never changes the answer."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import time

import pytest
from starlette.requests import Request

from app import connector_account_shadow as shadow
from app import connector_account_subject as proof
from app.config import Settings
from app.control_plane_identity import IdentityBridgeError
from app.control_plane_identity_worker import CloudflareControlPlaneIdentityAuthority
from app.identity_call_cache import CachedIdentityAuthority
from app.shared_auth_adapter import SharedChatAuth, SharedAuthUnavailable
from app.session_revocation_guard import SessionVerdict, SESSION_VERDICT_STATE_KEY
from padiem_control_plane import CanonicalSubjectRef, SubjectType
from padiem_control_plane.auth_sessions import AuthSessionSnapshot

PRIVATE = "sub_private_account_fixture"
SID = "private-session-fixture"
TENANT = "private-tenant-fixture"
NOW = datetime.now(timezone.utc)
SESSION = AuthSessionSnapshot(session_id=SID, product_id="b62",
    subject=CanonicalSubjectRef(subject_type=SubjectType.USER, subject_id=PRIVATE),
    issued_at=NOW-timedelta(minutes=1), expires_at=NOW+timedelta(minutes=10), tenant_id=TENANT)
BASELINE = {
    "owner_scope":{"account_ref":"private-account-scope", "workspace_ref":"private-workspace", "owner_subject_id":PRIVATE},
    "workspace":{"present":True, "workspace_ref":"private-workspace"},
    "context":{"present":True, "product_id":"b62", "subject_id":PRIVATE, "actor_ref":"private-actor", "workspace_ref":"private-workspace"},
    "consent":{"consent_id":"private-consent", "device_id":"private-device", "owner_subject_id":PRIVATE,
               "account_ref":"private-account-scope", "workspace_ref":"private-workspace",
               "granted_at":NOW.isoformat(), "withdrawn_at":None},
}
SESSION_METHOD = {"owner_scope":"resolve_connector_owner_scope", "workspace":"resolve_connector_workspace",
    "context":"resolve_connector_context", "consent":"resolve_connector_enrollment_consent_for_device"}


class Binding:
    _timeout = .03
    def __init__(self):
        self.calls=[];self.alternate=deepcopy(BASELINE);self.original=deepcopy(BASELINE)
        self.tenants=[TENANT];self.error=None;self.session_error=None;self.wait=None;self.started=asyncio.Event()
        self.session=SESSION;self.session_wait=None
    def __getattr__(self, name):
        async def call(payload):
            self.calls.append((name,deepcopy(payload)))
            if name in {"resolve_auth_session","resolve_current_auth_session"}:
                return {"ok":True,"session":self.session.to_public_dict()}
            if name == "resolve_product_user_for_subject":
                return {"ok":True,"product_user_id":"usr_fixture"}
            if name == "resolve_active_memberships":
                return {"ok":True,"tenant_ids":self.tenants}
            for kind,(account_name,field) in shadow.ACCOUNT_READS.items():
                account = name == account_name
                if account or name == SESSION_METHOD[kind]:
                    if account:
                        self.started.set()
                        if self.wait is not None:
                            await self.wait()
                        if isinstance(self.error, BaseException):
                            raise self.error
                        if self.error is not None:
                            return deepcopy(self.error)
                    elif self.session_error is not None:
                        return {"ok":False,"error":{"code":self.session_error,"message":"unavailable"}}
                    elif self.session_wait is not None:
                        await self.session_wait()
                    return {"ok":True,field:deepcopy((self.alternate if account else self.original)[kind])}
            raise AssertionError("unexpected_fixture_rpc")
        return call


class Verifier:
    def verify(self, _token):
        return {"accountId":PRIVATE,"sessionId":"private-shared-session","expiresAt":int(time.time())+600}


async def in_request(binding, callback, *, enabled=True, cache=False, metadata=True, verifier=None):
    authority=CloudflareControlPlaneIdentityAuthority(binding)
    authority=CachedIdentityAuthority(authority) if cache else authority
    auth=SharedChatAuth(verifier=verifier or Verifier(),authority=authority,legacy=lambda _r:None)
    state=SimpleNamespace(auth_validation_cache=None,settings=Settings())
    scope={"type":"http","path":"/fixture","headers":[],"app":SimpleNamespace(state=state)}
    request=Request(scope)
    async def app(scope, _receive, _send):
        await auth.user_id(request,"synthetic-signed-access")
        if metadata:
            await authority.resolve_current_auth_session(product_id="b62",product_user_id="usr_fixture")
        await callback(authority,request)
    if enabled:
        await proof.ConnectorAccountShadowContextMiddleware(app)(scope,None,None)
    else:
        await app(scope,None,None)
    assert proof.shadow_context_enabled() is False
    return authority


async def settled():
    for _ in range(20):
        tasks=tuple(shadow._BACKGROUND)
        if not tasks:return
        await asyncio.gather(*tasks,return_exceptions=True)
        await asyncio.sleep(0)  # Dispatch done callbacks for already-cancelled tasks.
    assert not shadow._BACKGROUND


async def read(authority, kind, *, session_id=SID):
    kwargs={"session_id":session_id}
    if kind=="consent":kwargs["device_id"]="private-device"
    return await getattr(authority,SESSION_METHOD[kind])(**kwargs)


@pytest.mark.parametrize("kind",shadow.ACCOUNT_READS)
async def test_off_has_no_extra_rpc_and_preserves_the_session_answer(kind,capsys):
    binding=Binding();answers=[]
    async def call(authority,_request):answers.append(await read(authority,kind))
    await in_request(binding,call,enabled=False);await settled()
    assert [name for name,_ in binding.calls]==["resolve_product_user_for_subject","resolve_current_auth_session",SESSION_METHOD[kind]]
    assert answers[0] == (BASELINE[kind]["workspace_ref"] if kind=="workspace" else BASELINE[kind])
    assert "connector_account_shadow" not in capsys.readouterr().out


@pytest.mark.parametrize("kind",shadow.ACCOUNT_READS)
async def test_existing_read_shadows_the_typed_verified_account_without_changing_its_result(kind,capsys):
    binding=Binding();answers=[]
    async def call(authority,_request):answers.append(await read(authority,kind))
    await in_request(binding,call);await settled()
    sent=next(payload for name,payload in binding.calls if name==shadow.ACCOUNT_READS[kind][0])
    assert sent=={"product_id":"b62","canonical_subject_id":PRIVATE,**({"device_id":"private-device"} if kind=="consent" else {})}
    assert answers[0] == (BASELINE[kind]["workspace_ref"] if kind=="workspace" else BASELINE[kind])
    assert capsys.readouterr().out.splitlines()==["connector_account_shadow method="+kind+" reason=match"]


@pytest.mark.parametrize("change,reason",[
    ("scope","scope_mismatch"),("tenant","tenant_mismatch"),("ambiguous","membership_denied"),
    ("missing","membership_denied"),("denial","session_allow_account_deny"),
    ("disabled","account_disabled"),("invalid","account_invalid"),("exception","account_unavailable")])
async def test_shadow_disagreements_and_failures_leave_original_response_unchanged(change,reason,capsys,caplog):
    binding=Binding()
    if change=="scope":binding.alternate["workspace"]["workspace_ref"]="private-other-workspace"
    if change=="tenant":binding.tenants=["private-other-tenant"]
    if change=="ambiguous":binding.tenants=[TENANT,"private-other-tenant"]
    if change=="missing":binding.tenants=[]
    if change in {"denial","disabled"}:
        binding.error={"ok":False,"error":{"code":"connector_account_key_rpc_disabled" if change=="disabled" else PRIVATE,"message":SID+TENANT}}
    if change=="invalid":binding.error={"ok":True,"workspace":{"present":True,"workspace_ref":PRIVATE,"unexpected":SID}}
    if change=="exception":binding.error=RuntimeError(PRIVATE+SID+TENANT)
    async def call(authority,_request):assert await read(authority,"workspace")=="private-workspace"
    await in_request(binding,call);await settled()
    output=capsys.readouterr().out+caplog.text
    assert output.strip()=="connector_account_shadow method=workspace reason="+reason
    assert all(value not in output for value in (PRIVATE,SID,TENANT,"private-other"))


async def test_session_deny_account_allow_keeps_the_same_original_exception(capsys):
    binding=Binding();binding.session_error="inactive_auth_session"
    async def call(authority,_request):
        with pytest.raises(IdentityBridgeError) as caught:await read(authority,"workspace")
        assert caught.value.code=="inactive_auth_session";assert caught.value.status_code==401
    await in_request(binding,call);await settled()
    assert capsys.readouterr().out.strip()=="connector_account_shadow method=workspace reason=session_deny_account_allow"


@pytest.mark.parametrize("code,reason",[("inactive_auth_session","denial_match"),("canonical_subject_deleted","denial_mismatch")])
async def test_denials_compare_only_closed_codes(code,reason,capsys):
    binding=Binding();binding.session_error="inactive_auth_session"
    binding.error={"ok":False,"error":{"code":code,"message":PRIVATE}}
    async def call(authority,_request):
        with pytest.raises(IdentityBridgeError):await read(authority,"workspace")
    await in_request(binding,call);await settled()
    assert capsys.readouterr().out.strip().endswith("reason="+reason)


async def test_metadata_absence_is_never_claimed_as_a_tenant_match(capsys):
    binding=Binding()
    async def call(authority,_request):await read(authority,"workspace")
    await in_request(binding,call,metadata=False);await settled()
    assert capsys.readouterr().out.strip().endswith("reason=tenant_unavailable")


async def test_cache_hit_retains_verified_session_metadata_and_cache_keys_unchanged(capsys):
    binding=Binding();cached=CachedIdentityAuthority(CloudflareControlPlaneIdentityAuthority(binding))
    await cached.resolve_current_auth_session(product_id="b62",product_user_id="usr_fixture")
    keyset=set(cached._entries)
    async def call(_authority,_request):
        await cached.resolve_current_auth_session(product_id="b62",product_user_id="usr_fixture")
        await cached.resolve_connector_owner_scope(session_id=SID)
    await in_request(binding,call,metadata=False);await settled()
    assert capsys.readouterr().out.strip().endswith("reason=match")
    assert sum(name=="resolve_current_auth_session" for name,_ in binding.calls)==1
    assert keyset <= set(cached._entries)
    assert all(key.startswith(("authsession:","ownerscope:")) for key in cached._entries)


async def test_slow_shadow_never_holds_the_response_even_if_transport_ignores_cancellation(capsys):
    binding=Binding();release=asyncio.Event()
    async def stubborn():
        try:await release.wait()
        except asyncio.CancelledError:await release.wait()
    binding.wait=stubborn
    async def call(authority,_request):
        assert await read(authority,"workspace")=="private-workspace"
        assert not binding.started.is_set(),"comparison starts after the existing response path returns"
    await in_request(binding,call)
    await binding.started.wait();await asyncio.sleep(.06)
    assert "reason=timeout" in capsys.readouterr().out
    release.set();await settled()


async def test_worker_scheduler_owns_the_background_and_receives_no_request_object(capsys):
    from app.request_telemetry import install_export_scheduler,reset_export_scheduler
    pending=[];token=install_export_scheduler(pending.append);binding=Binding()
    try:
        async def call(authority,_request):await read(authority,"workspace")
        await in_request(binding,call)
    finally:reset_export_scheduler(token)
    assert len(pending)==1;assert not binding.started.is_set()
    await pending[0];await settled();assert "reason=match" in capsys.readouterr().out


async def test_direct_api_is_default_off_and_rejects_raw_account_input():
    binding=Binding();authority=CloudflareControlPlaneIdentityAuthority(binding)
    with pytest.raises(shadow.AccountReadError,match="disabled"):
        await authority.resolve_connector_workspace_for_subject(subject=PRIVATE)
    assert not binding.calls
    async def call(authority,_request):
        with pytest.raises(ValueError,match="verified_connector_subject_required"):
            await authority.resolve_connector_workspace_for_subject(subject=PRIVATE)
        with pytest.raises((TypeError,ValueError)):
            proof.VerifiedConnectorSubject(subject_id=PRIVATE)
        subject=proof.subject_for_connector_read(SID,"workspace")
        assert repr(subject)=="VerifiedConnectorSubject()"
        binding.error=RuntimeError(PRIVATE+SID)
        with pytest.raises(shadow.AccountReadError) as caught:
            await authority.resolve_connector_workspace_for_subject(subject=subject)
        assert PRIVATE not in repr(caught.value) and SID not in repr(caught.value)
    await in_request(binding,call)


async def test_owned_record_extension_checks_existing_verdict_and_database_row():
    from app.d1_sqlite import SqliteD1
    import sqlite3
    connection=sqlite3.connect(":memory:");connection.row_factory=sqlite3.Row
    connection.execute("CREATE TABLE users(id TEXT,provider_subject TEXT)")
    connection.execute("INSERT INTO users VALUES(?,?)",("usr_fixture","shared:"+PRIVATE))
    db=SqliteD1(connection)
    async def call(_authority,request):
        request.app.state.account_data_db=db
        request.scope["state"]={SESSION_VERDICT_STATE_KEY:SessionVerdict(True,"usr_fixture",SID,"active")}
        subject=await proof.subject_from_authenticated_owner_record(request,SESSION)
        assert subject.subject_id==PRIVATE and subject.tenant_id==TENANT
        request.scope["state"][SESSION_VERDICT_STATE_KEY]=SessionVerdict(False,reason="revoked")
        with pytest.raises(ValueError,match="verified_connector_subject_required"):
            await proof.subject_from_authenticated_owner_record(request,SESSION)
    await in_request(Binding(),call);connection.close()


def test_default_off_setting_projects_through_host_and_worker(monkeypatch):
    from app.worker_config import settings_from_worker_bindings
    assert Settings().connector_account_shadow_enabled is False
    assert Settings.from_values().connector_account_shadow_enabled is False
    monkeypatch.delenv("PADIEM_CHAT_CONNECTOR_ACCOUNT_SHADOW_ENABLED",raising=False)
    assert Settings.from_env().connector_account_shadow_enabled is False
    monkeypatch.setenv("PADIEM_CHAT_CONNECTOR_ACCOUNT_SHADOW_ENABLED","true")
    assert Settings.from_env().connector_account_shadow_enabled is True
    assert settings_from_worker_bindings(SimpleNamespace(PADIEM_CHAT_CONNECTOR_ACCOUNT_SHADOW_ENABLED="true")).connector_account_shadow_enabled is True


@pytest.mark.parametrize("failure",["exception","expired","missing_link","empty","legacy"])
async def test_failed_or_legacy_reauthentication_cannot_reuse_the_previous_proof(failure,capsys):
    binding=Binding()
    class RejectedVerifier:
        def verify(self,_token):
            if failure=="exception":raise ValueError(PRIVATE)
            return {"accountId":PRIVATE,"sessionId":SID,"expiresAt":0 if failure=="expired" else int(time.time())+60}
    class MissingLink:
        async def resolve_product_user_for_subject(self,**_kwargs):return None
    async def call(authority,request):
        assert proof.subject_for_connector_read(SID,"workspace") is not None
        rejected=SharedChatAuth(verifier=RejectedVerifier(),authority=MissingLink(),legacy=lambda _request:"usr_fixture")
        token=None if failure=="legacy" else "" if failure=="empty" else "synthetic-rejected-access"
        if failure=="legacy":
            assert await rejected.user_id(request,token)=="usr_fixture"
        else:
            with pytest.raises(SharedAuthUnavailable):await rejected.user_id(request,token)
        assert proof.subject_for_connector_read(SID,"workspace") is None
        await read(authority,"workspace")
    await in_request(binding,call);await settled()
    assert not any(name in {item[0] for item in shadow.ACCOUNT_READS.values()} for name,_ in binding.calls)
    assert capsys.readouterr().out.strip().endswith("reason=subject_unavailable")


@pytest.mark.parametrize("concurrent",[False,True])
async def test_request_and_background_proofs_stay_bound_to_each_verified_account(concurrent,capsys):
    bindings=[];ready=0;release=asyncio.Event()
    async def one(index):
        nonlocal ready
        subject="sub_distinct_fixture_"+str(index);session_id="distinct-session-"+str(index)
        binding=Binding();bindings.append(binding)
        binding.session=replace(SESSION,session_id=session_id,
            subject=CanonicalSubjectRef(subject_type=SubjectType.USER,subject_id=subject))
        for response in (binding.original,binding.alternate):
            response["owner_scope"]["owner_subject_id"]=subject
        verifier=SimpleNamespace(verify=lambda _token:{"accountId":subject,"sessionId":session_id,"expiresAt":int(time.time())+60})
        async def call(authority,_request):
            nonlocal ready
            if concurrent:
                ready+=1
                if ready==2:release.set()
                await release.wait()
            assert proof.subject_for_connector_read(session_id,"owner_scope").subject_id==subject
            await read(authority,"owner_scope",session_id=session_id)
        await in_request(binding,call,verifier=verifier)
    if concurrent:await asyncio.gather(one(1),one(2))
    else:
        await one(1);await one(2)
    await settled()
    for binding in bindings:
        payload=next(payload for name,payload in binding.calls if name==shadow.ACCOUNT_READS["owner_scope"][0])
        assert payload["canonical_subject_id"]==binding.session.subject.subject_id
    assert capsys.readouterr().out.splitlines()==["connector_account_shadow method=owner_scope reason=match"]*2
    assert proof.subject_for_connector_read(SID,"workspace") is None


async def test_observation_counter_and_logger_failures_do_not_change_the_response(monkeypatch):
    binding=Binding()
    def broken(*_args,**_kwargs):raise RuntimeError(PRIVATE+SID+TENANT)
    monkeypatch.setattr(shadow,"record_rpc",broken)
    monkeypatch.setattr("builtins.print",broken)
    async def call(authority,_request):assert await read(authority,"workspace")=="private-workspace"
    await in_request(binding,call);await settled()
    assert binding.started.is_set()


async def test_request_cancellation_is_preserved_and_does_not_start_a_comparison():
    binding=Binding();waiting=asyncio.Event();release=asyncio.Event()
    async def wait():waiting.set();await release.wait()
    binding.session_wait=wait
    async def call(authority,_request):await read(authority,"workspace")
    task=asyncio.create_task(in_request(binding,call))
    await waiting.wait();task.cancel()
    with pytest.raises(asyncio.CancelledError):await task
    await settled();assert not binding.started.is_set()
    assert not proof.shadow_context_enabled()


async def test_external_background_cancellation_propagates_and_cancels_its_transport(capsys):
    binding=Binding();cancelled=asyncio.Event();release=asyncio.Event()
    async def wait():
        try:await release.wait()
        finally:cancelled.set()
    binding.wait=wait
    async def call(authority,_request):await read(authority,"workspace")
    await in_request(binding,call);await binding.started.wait()
    observation=next(task for task in shadow._BACKGROUND if task.get_coro().__name__=="_observe_safely")
    observation.cancel()
    with pytest.raises(asyncio.CancelledError):await observation
    await settled();assert cancelled.is_set()
    assert "connector_account_shadow" not in capsys.readouterr().out


@pytest.mark.parametrize("enabled",[False,True])
async def test_app_factory_switch_wraps_the_existing_authenticated_read(enabled,capsys):
    import httpx
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from app.app_factory import create_app
    binding=Binding();authority=CloudflareControlPlaneIdentityAuthority(binding)
    auth=SharedChatAuth(verifier=Verifier(),authority=authority,legacy=lambda _request:None)
    app=create_app(Settings.from_values(connector_account_shadow_enabled=enabled))
    app.state.auth_validation_cache=None
    async def endpoint(request):
        await auth.user_id(request,"synthetic-signed-access")
        await authority.resolve_current_auth_session(product_id="b62",product_user_id="usr_fixture")
        result=await read(authority,"workspace")
        assert not binding.started.is_set()
        return JSONResponse({"workspace":result})
    app.router.routes.insert(0,Route("/api/fixture/connector",endpoint,methods=["GET"]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="https://fixture.invalid") as client:
        response=await client.get("/api/fixture/connector")
    assert response.status_code==200 and response.json()=={"workspace":"private-workspace"}
    await settled()
    assert binding.started.is_set() is enabled
    lines=[line for line in capsys.readouterr().out.splitlines() if line.startswith("connector_account_shadow ")]
    assert lines==(["connector_account_shadow method=workspace reason=match"] if enabled else [])
