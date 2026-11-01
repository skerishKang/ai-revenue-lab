"""BYOK(PADIEM Custom) 공격 시험 — 11-02 운영에서 켜지는 사용자 키·엔드포인트 레인.

모의 대역만 사용한다: 실제 공급사 호출, 실제 외부 접속(DoH 포함), 컴2 접속 없음.
기존 #5002 제품 E2E 헤널스(실 ASGI 앱 + SQLite D1 + MockTransport + 봉인 암호
대역)를 재사용해 실제 라우트·저장·해제·호출 경로를 돌린다.

판정 규칙(지시서): 막힘(통과) → 고정, 뚫림(결함) → xfail 관측, 서버가 판단할 수
없는 것 → 판단 불가 기록. 단, 결함의 뿌리가 #6627에서 고친 것과 같으면 같은
방식으로 고쳐 정상 단언한다.

엔드포인트 권위는 web_runtime과 **별도**다: apps/padiem-chat/app/byok_endpoint.py
가 자체 _NUMERIC_HOST(16진·10진)·라벨 isdigit·IP 리터럴·포트·쿼리 검사를 하고,
DNS 계층(verify_public_endpoint)에서 모든 A/AAAA 답이 공개 유니캐스트인지 증명한다
— 16진수 IP는 이미 막혀 있었다(컴2 관측 422 재현). 리다이렉트는 클라이언트가
follow_redirects=False + 3xx 거부로 막는다(판단 불가가 아니라 통과).

판단 불가로 기록한 것: 등록·호출 시점 DNS 검증 사이의 리바인딩 창(60초 캐시 +
호출 시 재검증이 완화하나 연결 시점 IP 고정은 아님 — 설계 한계, 보고 표 참조).
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from app.byok_bridge import UserCredentialReference
from app.byok_client import CustomProviderClient
from app.byok_credentials import CustomCredentialDecryptionError
from app.byok_endpoint import (
    CustomEndpointError,
    CustomEndpointUnverifiedError,
    CustomEndpointVerificationError,
    normalize_custom_endpoint,
    verify_public_endpoint,
)

from pathlib import Path

from test_5002_byok_product_e2e import (
    CUSTOM_KEY,
    OTHER,
    OWNER,
    PROVIDER_ID,
    request,
    settings,
)
from test_5002_byok_product_e2e import (
    B14Probe,
    D1CustomProviderCredentialStore,
    FakeAuthenticatedCipher,
    ProviderRecorder,
)
from app.history import D1HistoryStore
from app.main import create_app

ORIGIN = "https://chat.example.test"
CREDENTIAL_PATH = "/api/chat/custom/credential"
SAVED_KEY_LAST4 = CUSTOM_KEY[-4:]
DEFAULT_ENDPOINT = "https://opencode.ai/inference/go/v1"
MODELS_PROVIDER = "deepseek"          # models_path='models' — 실제 공급사 호출이 나간다
MODELS_DEFAULT_ENDPOINT = "https://api.deepseek.com"


def build_app():
    """#5002 헤널스 + 064(endpoint 컬럼) — BYOK 엔드포인트 장면이 필요로 하는 조합."""
    import sqlite3
    from pathlib import Path

    import test_5002_byok_product_e2e as base

    d1 = base.SQLiteD1()
    d1.conn.executescript((Path(__file__).resolve().parents[1] / "migrations"
                           / "064_chat_custom_provider_endpoints.sql").read_text(encoding="utf-8"))
    history = D1HistoryStore(d1)
    credential_store = D1CustomProviderCredentialStore(
        d1,
        key_secret=base.CUSTOM_KEY_SECRET,
        session_secret=base.SESSION_SECRET,
        cipher=FakeAuthenticatedCipher(),
    )
    recorder = ProviderRecorder()
    app = create_app(
        settings(),
        history_store=history,
        custom_credential_store=credential_store,
        custom_provider_client=CustomProviderClient(transport=recorder.transport),
    )
    app.state.b14_client = B14Probe()
    app.state.b14_catalog_source = None
    app.state.central_model_policy_store = None
    app.state.usage_gate_enforced = False
    return app, d1, history, credential_store, recorder


class FakeResolver:
    """Scriptable DNS evidence: what the DoH resolver would answer."""

    def __init__(self, answers=None, error=None):
        self.answers = answers or ()
        self.error = error
        self.asked: list[str] = []

    async def resolve(self, hostname: str) -> tuple[str, ...]:
        self.asked.append(hostname)
        if self.error is not None:
            raise self.error
        return tuple(self.answers)


def custom_client(transport, resolver):
    return CustomProviderClient(transport=transport, endpoint_resolver=resolver)


# ── 1) 엔드포인트 SSRF: normalize_custom_endpoint ───────────────────────────

ENDPOINT_REFUSALS = [
    "http://api.openai.com/v1",                       # HTTPS 전용
    "ftp://api.openai.com/", "javascript:alert(1)",
    "file:///C:/windows/win.ini", "data:text/html,x",
    "https://127.0.0.1/v1", "https://10.1.2.3/v1",
    "https://172.16.0.9/v1", "https://192.168.1.1/v1",
    "https://169.254.169.254/latest/meta-data/",
    "https://[::1]/v1", "https://[::ffff:127.0.0.1]/v1",
    "https://0.0.0.0/v1",
    # 16진수·8진수·십진수 정수 IP — 이 레인의 자체 검사(_NUMERIC_HOST·라벨 isdigit)
    "https://0x7f000001/v1", "https://0X7F000001/v1",
    "https://0x7f.0.0.1/v1", "https://2130706433/v1",
    "https://017700000001/v1", "https://0177.0.0.1/v1",
    "https://0x7f000001./v1",
    # userinfo — '@' 자체가 netloc에서 금지
    "https://good.com@127.0.0.1/v1", "https://owner@public.example/v1",
    # 포트 — 443만
    "https://api.openai.com:22/v1", "https://api.openai.com:8443/v1",
    # 쿼리·조각
    "https://api.openai.com/v1?x=1", "https://api.openai.com/v1#frag",
    # 제어 문자·공백·백슬래시·초과 길이
    "https://api.openai.com/\tx", "https://api.openai.com/ x",
    "https://api.openai.com/\\evil", "https://" + "a" * 3000 + ".com/",
    # 내부 접미·호스트
    "https://proxy.corp.internal/v1", "https://metadata.google.internal/",
    "https://box.localhost/v1",
]


@pytest.mark.parametrize("value", ENDPOINT_REFUSALS)
def test_hostile_endpoints_are_refused_before_a_key_is_stored(value):
    # 거부 메시지는 모양마다 다르다(단일 라벨 → "호스트가 올바르지 않습니다",
    # 숫자 라벨 혼합 → "IP 주소 형식") — 거부 자체가 이 시험의 계약이다.
    with pytest.raises(CustomEndpointError):
        normalize_custom_endpoint(value, default_endpoint=DEFAULT_ENDPOINT)


def test_endpoint_authority_is_byok_own_check_not_the_web_runtime_one():
    """CTO 질의: 16진수 IP가 #6627에서 고친 web_runtime 권위를 공유하는가?

    아니다 — 이 레인은 자체 검사(byok_endpoint._NUMERIC_HOST·라벨 isdigit·IP
    리터럴 거부)를 갖고, 점 구분 16진 혼합(0x7f.0.0.1)을 'IP 주소 형식'으로,
    단일 16진 표기(0x7f000001)를 '호스트가 올바르지 않습니다'로 거부한다.
    web_runtime(#6627 수정)과 독립된 검사이며 양쪽 모두 같은 우회를 막는다."""
    with pytest.raises(CustomEndpointError) as dotted:
        normalize_custom_endpoint("https://0x7f.0.0.1/v1", default_endpoint=DEFAULT_ENDPOINT)
    assert "IP 주소 형식" in str(dotted.value)
    with pytest.raises(CustomEndpointError):
        normalize_custom_endpoint("https://0x7f000001/v1", default_endpoint=DEFAULT_ENDPOINT)
    source = Path(__file__).resolve().parents[1].joinpath("app", "byok_endpoint.py").read_text(
        encoding="utf-8")
    assert '_NUMERIC_HOST = re.compile(r"^(?:0x[0-9a-f]+|[0-9]+)$"' in source


def test_https_port_443_and_paths_stay_allowed():
    ok = normalize_custom_endpoint("https://api.openai.com:443/v1", default_endpoint=DEFAULT_ENDPOINT)
    assert ok == "https://api.openai.com/v1"
    ok = normalize_custom_endpoint("https://api.openai.com/v1/", default_endpoint=DEFAULT_ENDPOINT)
    assert ok == "https://api.openai.com/v1"


def test_dns_layer_blocks_private_and_mixed_answers():
    default = DEFAULT_ENDPOINT
    # 공개 DNS가 내부를 가리키는 이름(nip.io 등)도 DNS 답 자체가 증거다 — 판단 불가가 아니라 막힌다.
    for answers in (("127.0.0.1",), ("10.0.0.8",), ("169.254.169.254",),
                    ("::1",), ("::ffff:127.0.0.1",), ("8.8.8.8", "192.168.0.1")):
        with pytest.raises(CustomEndpointVerificationError):
            import asyncio
            asyncio.run(verify_public_endpoint(
                "https://rebound.example/v1", default_endpoint=default,
                resolver=FakeResolver(answers=answers)))
    import asyncio
    allowed = asyncio.run(verify_public_endpoint(
        "https://rebound.example/v1", default_endpoint=default,
        resolver=FakeResolver(answers=("93.184.216.34",))))
    assert allowed == "https://rebound.example/v1"
    # DNS 실패는 실패로 닫힌다(열어 주지 않는다).
    with pytest.raises(CustomEndpointUnverifiedError):
        asyncio.run(verify_public_endpoint(
            "https://rebound.example/v1", default_endpoint=default,
            resolver=FakeResolver(error=RuntimeError("dns down"))))


def test_save_route_blocks_internal_and_integer_endpoints(lane=None):
    app, d1, _history, _store, _recorder = build_app()
    for endpoint in ("http://127.0.0.1/v1", "https://0x7f000001/v1",
                     "https://169.254.169.254/v1", "https://api.openai.com:22/v1"):
        answer = _put(app, {"provider": PROVIDER_ID, "api_key": CUSTOM_KEY,
                            "endpoint": endpoint})
        assert answer.status_code == 422, (endpoint, answer.text)
    assert d1.sealed_credentials() == []  # 아무 봉인도 생기지 않았다


def _put(app, body, uid=OWNER):
    import asyncio
    return asyncio.run(request(app, "PUT", CREDENTIAL_PATH, uid=uid, json_body=body))


# ── 2) 키 유출: 응답·오류·SSE·DB 어디에도 평문이 없다 ───────────────────────


@pytest.mark.asyncio
async def test_status_and_save_responses_never_carry_key_material():
    app, d1, _history, _store, _recorder = build_app()
    saved = await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                          json_body={"provider": PROVIDER_ID, "api_key": CUSTOM_KEY})
    assert saved.status_code == 200, saved.text
    body = saved.text
    assert CUSTOM_KEY not in body and CUSTOM_KEY[-8:] not in body
    status = await request(app, "GET", CREDENTIAL_PATH, uid=OWNER)
    status_text = status.text
    assert CUSTOM_KEY not in status_text
    assert SAVED_KEY_LAST4 in status_text          # 마지막 4자는 계약상 노출된다
    assert "sealed_credential" not in status_text  # 봉인문도 응답에 없다
    assert "endpoint" in status_text


@pytest.mark.asyncio
async def test_database_stores_only_the_sealed_blob_and_last4():
    app, d1, _history, _store, _recorder = build_app()
    await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                  json_body={"provider": PROVIDER_ID, "api_key": CUSTOM_KEY,
                             "endpoint": "https://api.openai.com/v1"})
    rows = [dict(r) for r in d1.conn.execute(
        "SELECT * FROM chat_custom_provider_credentials")]
    assert len(rows) == 1
    dumped = json.dumps(rows, ensure_ascii=False)
    assert CUSTOM_KEY not in dumped and CUSTOM_KEY[:-4] not in dumped
    blob = rows[0]["sealed_credential"]
    assert base64.b64decode(blob, validate=True)[:12] != b""  # iv+암호문 봉인
    assert CUSTOM_KEY.encode() not in base64.b64decode(blob)   # 봉인문에도 평문 없음(실제 GCM 대역)
    assert rows[0]["key_last4"] == SAVED_KEY_LAST4


@pytest.mark.asyncio
async def test_provider_auth_error_never_echoes_the_key():
    app, _d1, _history, _store, recorder = build_app()
    recorder._handler = lambda request: httpx.Response(
        401, json={"error": {"message": "bad key " + CUSTOM_KEY}})
    await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                  json_body={"provider": MODELS_PROVIDER, "api_key": CUSTOM_KEY})
    answer = await request(app, "GET", "/api/chat/custom/models?provider=" + MODELS_PROVIDER,
                           uid=OWNER)
    assert answer.status_code == 502
    assert CUSTOM_KEY not in answer.text
    assert "공급사가 API 키를 거부했습니다" in answer.text


def test_credential_reference_repr_is_redacted():
    ref = UserCredentialReference(json.dumps(
        {"provider": PROVIDER_ID, "key": CUSTOM_KEY}, separators=(",", ":")))
    assert CUSTOM_KEY not in repr(ref)
    assert repr(ref) == "UserCredentialReference(<redacted>)"


def test_byok_modules_never_log_key_material():
    import pathlib
    for name in ("byok_routes.py", "byok_credentials.py", "byok_client.py",
                 "byok_bridge.py", "byok_endpoint.py"):
        source = (pathlib.Path(__file__).resolve().parents[1] / "app" / name).read_text(
            encoding="utf-8")
        for forbidden in ("logger", "logging", "print(", "console.log"):
            assert forbidden not in source, (name, forbidden)


# ── 3) 계정 격리 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_other_account_sees_nothing_and_cannot_delete_owners_credential():
    app, d1, _history, store, _recorder = build_app()
    await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                  json_body={"provider": PROVIDER_ID, "api_key": CUSTOM_KEY})
    other_status = await request(app, "GET", CREDENTIAL_PATH, uid=OTHER)
    assert other_status.json()["credentials"] == []
    deleted = await request(app, "DELETE",
                            CREDENTIAL_PATH + "?provider=" + PROVIDER_ID, uid=OTHER)
    assert deleted.status_code == 200
    # 관측(표면): 없는 행에 대한 삭제도 deleted=true로 답한다(소유 스코프 밖 행은
    # 건드리지 않았다는 뜻 — 아래 온전성이 진짜 증거다).
    assert await store.api_key(OWNER, PROVIDER_ID) == CUSTOM_KEY  # 소유자 것은 온전
    owner_status = await request(app, "GET", CREDENTIAL_PATH, uid=OWNER)
    assert owner_status.json()["credentials"][0]["key_last4"] == SAVED_KEY_LAST4


@pytest.mark.asyncio
async def test_other_account_conversation_never_uses_owners_key():
    app, _d1, _history, _store, recorder = build_app()
    await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                  json_body={"provider": PROVIDER_ID, "api_key": CUSTOM_KEY})
    answer = await request(app, "POST", "/api/chat", uid=OTHER, json_body={
        "messages": [{"role": "user", "content": "안녕"}],
        "custom": {"provider": PROVIDER_ID, "model": "opencode-go/beam-free"}})
    assert answer.status_code in (409, 402, 400), answer.text
    assert recorder.requests == []  # 소유자 키로 단 한 번도 호출되지 않았다


@pytest.mark.asyncio
async def test_endpoint_only_mutation_is_impossible_via_the_save_route():
    app, d1, _history, _store, recorder = build_app()
    await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                  json_body={"provider": PROVIDER_ID, "api_key": CUSTOM_KEY,
                             "endpoint": "https://api.openai.com/v1"})
    # 엔드포인트만 바꾸는 요청: 키 없는 몸 — 닫힌 몸 계약이 거부한다.
    only_endpoint = await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                                  json_body={"provider": PROVIDER_ID,
                                             "endpoint": "https://evil.example/v1"})
    assert only_endpoint.status_code == 422
    row = dict(list(d1.conn.execute(
        "SELECT endpoint, sealed_credential FROM chat_custom_provider_credentials"))[0])
    assert row["endpoint"] == "https://api.openai.com/v1"  # 엔드포인트는 그대로


@pytest.mark.asyncio
async def test_endpoint_mutation_without_reseal_cannot_reuse_the_key():
    """AAD 핀: 봉인은 사용자·공급사·엔드포인트에 묶여 있다 — 엔드포인트 열만
    바뀐 봉인문은 해제되지 않고, 고정된 한국어 오류만 나온다(키 재입력 필요)."""
    app, d1, _history, store, _recorder = build_app()
    await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                  json_body={"provider": PROVIDER_ID, "api_key": CUSTOM_KEY,
                             "endpoint": "https://api.openai.com/v1"})
    d1.conn.execute("UPDATE chat_custom_provider_credentials SET endpoint=?",
                    ("https://evil.example/v1",))
    d1.conn.commit()
    try:
        await store.credential(OWNER, PROVIDER_ID)
        raise AssertionError("endpoint-mutated seal must not decrypt")
    except CustomCredentialDecryptionError as exc:
        assert CUSTOM_KEY not in str(exc)
        assert "could not be decrypted" in str(exc)


# ── 4) 입력 폭탄 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_key_length_and_charset_bounds():
    app, _d1, _history, _store, _recorder = build_app()
    for bad in ("k" * 15, "k" * 513, "k\0" * 8, "k k" * 6, "키" * 16, "k\n" * 8):
        answer = await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                               json_body={"provider": PROVIDER_ID, "api_key": bad})
        assert answer.status_code == 422, (bad[:12], answer.text)
    assert (await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                          json_body={"provider": PROVIDER_ID, "api_key": "k" * 16})
            ).status_code == 200
    assert (await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                          json_body={"provider": PROVIDER_ID, "api_key": "k" * 512})
            ).status_code == 200


@pytest.mark.asyncio
async def test_provider_name_and_body_shape_spoofing_is_refused():
    app, _d1, _history, _store, _recorder = build_app()
    for provider in ("OpenAI", "openai ", " openai", "openai-x", 123, None, ["openai"]):
        answer = await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                               json_body={"provider": provider, "api_key": "k" * 20})
        assert answer.status_code == 422, (provider, answer.text)
    extras = await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER, json_body={
        "provider": PROVIDER_ID, "api_key": "k" * 20, "cookie": "steal"})
    assert extras.status_code == 422
    non_dict = await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER, json_body=["x"])
    assert non_dict.status_code == 422


def test_endpoint_input_bombs_are_bounded():
    for bad in ("https://" + "a" * 3000 + ".com/", "https://api.openai.com/\x00",
                "https://api.openai.com/\x1f범위", "https://api.openai.com/\rv1"):
        with pytest.raises(CustomEndpointError):
            normalize_custom_endpoint(bad, default_endpoint=DEFAULT_ENDPOINT)
    # 관측(안전한 방향): 끝에 붙은 제어 문자는 str.strip()이 검사 전에 벗겨
    # 깨끗한 origin으로 정규화된다 — 제어 문자가 저장되는 길은 없다.
    normalized = normalize_custom_endpoint("https://api.openai.com/v1\x1f",
                                           default_endpoint=DEFAULT_ENDPOINT)
    assert normalized == "https://api.openai.com/v1"
    assert "\x1f" not in normalized


# ── 5) 호출 시점 재검증·리다이렉트 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_time_revalidation_blocks_a_rebounded_endpoint():
    """등록 때 공개였어도 호출 시점 DNS 답이 내부로 돌면 502로 거부한다
    (60초 캐시를 우회하는 재검증 — 리바인딩 창의 완화 계약)."""
    app, _d1, _history, _store, recorder = build_app()
    client = custom_client(recorder.transport, FakeResolver(answers=("127.0.0.1",)))
    app.state.custom_provider_client = client
    await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                  json_body={"provider": MODELS_PROVIDER, "api_key": CUSTOM_KEY,
                             "endpoint": "https://api.deepseek.com/v1"})
    answer = await request(app, "GET", "/api/chat/custom/models?provider=" + MODELS_PROVIDER,
                           uid=OWNER)
    assert answer.status_code == 502
    assert CUSTOM_KEY not in answer.text
    assert recorder.requests == []  # 내부로 단 한 번도 나가지 않았다


@pytest.mark.asyncio
async def test_provider_redirect_is_blocked_without_following():
    app, _d1, _history, _store, recorder = build_app()
    recorder._handler = lambda request: httpx.Response(
        307, headers={"Location": "https://169.254.169.254/latest/meta-data/"})
    client = custom_client(recorder.transport, FakeResolver(answers=("93.184.216.34",)))
    app.state.custom_provider_client = client
    await request(app, "PUT", CREDENTIAL_PATH, uid=OWNER,
                  json_body={"provider": MODELS_PROVIDER, "api_key": CUSTOM_KEY})
    answer = await request(app, "GET", "/api/chat/custom/models?provider=" + MODELS_PROVIDER,
                           uid=OWNER)
    assert answer.status_code == 502
    assert "이동을 요청해 차단했습니다" in answer.text
    assert len(recorder.requests) == 1  # 리다이렉트를 따라간 요청은 없다
