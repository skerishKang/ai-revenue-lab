"""R7-3 from_values 단계 나누기 증거 시험 (#7814).

리팩터 전후 동일을 고정한다: 대표 입력으로 만든 설정 객체의 필드·값
(비밀 칸은 '있음/없음'만)과 오류 메시지가 리팩터 전 origin/main
(fb358229)에서 생성한 골든 표와 같다. 단계 하나를 바꾸면 이 시험이
실패한다. 실제 운영 설정 값·비밀값은 쓰지 않는다(가짜 값만).
"""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import pytest

from app.config import ConfigError, Settings

GOLDEN_PATH = Path(__file__).resolve().parent / "test_7814_config_from_values_table_golden.json"

SECRET_FIELDS = frozenset({
    "file_lane_ticket_secret",
    "firecrawl_api_key",
    "daum_rest_api_key",
    "tinyfish_api_key",
    "google_client_secret",
    "session_secret",
    "custom_key_secret",
    "custom_key_previous_secrets",
    "custom_key_legacy_session_secrets",
    "quota_salt",
    "account_delete_rpc_secret",
    "password_rpc_secret",
    "voice_rpc_secret",
})


def _field_value(name: str, value: object) -> object:
    if name in SECRET_FIELDS:
        return "있음" if value else "없음"
    if isinstance(value, tuple):
        return list(value)
    return value


def _settings_table(settings: Settings) -> dict:
    return {
        field.name: _field_value(field.name, getattr(settings, field.name))
        for field in dataclasses.fields(Settings)
    }


def _run_case(name: str, kwargs: dict) -> dict:
    try:
        settings = Settings.from_values(**kwargs)
    except ConfigError as exc:
        return {"case": name, "error": str(exc)}
    return {"case": name, "fields": _settings_table(settings)}


def _fake_secret(char: str, length: int = 40) -> str:
    return char * length


CASES = [
    ("빈_환경", {}),
    (
        "가짜_운영_모양",
        {
            "runtime_mode": "b14",
            "b14_base_url": "https://b14.example.test",
            "timeout_seconds": "123",
            "completed_timeout_seconds": 456,
            "live_enabled": "true",
            "web_provider": "tinyfish_daum",
            "firecrawl_api_key": "fake-firecrawl-key",
            "daum_rest_api_key": "fake-daum-key",
            "tinyfish_api_key": "fake-tinyfish-key",
            "web_timeout_seconds": "45",
            "auth_mode": "google",
            "public_base_url": "https://chat.example.test",
            "google_client_id": "fake-google-client-id",
            "google_client_secret": "fake-google-client-secret-value-123456",
            "session_secret": _fake_secret("s"),
            "byok_via_b14": "off",
            "custom_key_secret": _fake_secret("c"),
            "custom_key_previous_secrets": _fake_secret("p") + "," + _fake_secret("q"),
            "custom_key_legacy_session_secrets": _fake_secret("l"),
            "session_max_age_seconds": "86400",
            "cookie_secure": "no",
            "quota_salt": _fake_secret("q", 32),
            "anonymous_burst_limit": "5",
            "anonymous_daily_limit": "25",
            "user_burst_limit": "9",
            "user_daily_limit": "150",
            "global_daily_limit": "2000",
            "b66_quote_base_url": "https://quote.example.test",
            "file_lane_origin": "https://files.example.test",
            "file_lane_ticket_secret": _fake_secret("t"),
            "b14_upstream_mode": "binding",
            "public_base_urls": "https://chat.example.test, https://www.example.test",
            "local_dev": "1",
            "mcp_pc_shell_enabled": "true",
            "mcp_pc_shell_user_mode_enabled": "1",
            "mcp_pc_session_enabled": "true",
            "chat_pc_session_enabled": "true",
            "email_login_via_shared": "true",
            "session_user_row_check": "false",
            "mcp_pat_ttl_days": "120",
            "conversion_daily_limits": {"free": 11, "pro": 101},
            "conversion_max_bytes": '{"free": 1024}',
            "conversion_max_pages": {"admin": None, "free": 81},
            "local_verify_enabled": "true",
            "email_recovery_enabled": "true",
            "password_find_enabled": "true",
            "email_confirmation_enabled": "true",
            "feedback_daily_limit": "12",
            "feedback_max_chars": "5000",
            "site_feedback_daily_limit": "250",
            "lovetree_account_delete_url": "https://delete.example.test",
            "account_delete_rpc_secret": _fake_secret("a"),
            "password_rpc_secret": _fake_secret("p"),
            "voice_rpc_secret": _fake_secret("v"),
            "connector_account_shadow_enabled": "true",
            "connector_account_key_enabled": "true",
        },
    ),
    (
        "경계값",
        {
            "runtime_mode": "mock",
            "timeout_seconds": 1,
            "completed_timeout_seconds": 3600,
            "web_timeout_seconds": 60,
            "session_max_age_seconds": 300,
            "anonymous_burst_limit": 1,
            "global_daily_limit": 1000000,
            "conversion_daily_limits": {"free": 1},
            "conversion_max_pages": {"max": 100000},
            "mcp_pat_ttl_days": 1,
            "cookie_secure": False,
            "byok_via_b14": True,
            "live_enabled": False,
            "public_base_url": "http://127.0.0.1:8000",
            "local_dev": "1",
            "public_base_urls": "http://localhost:8000",
        },
    ),
    (
        "업스트림_HTTPS",
        {
            "runtime_mode": "b14",
            "b14_upstream_mode": "https",
            "b14_upstream_url": "https://b14.example.test",
        },
    ),
    ("모드_오류", {"runtime_mode": "nope"}),
    ("로컬_플래그_오류", {"local_dev": "yes"}),
    ("쉘_플래그_오류", {"mcp_pc_shell_enabled": "yes"}),
    ("쉘_사용자_플래그_오류", {"mcp_pc_shell_user_mode_enabled": "2"}),
    ("세션_플래그_오류", {"mcp_pc_session_enabled": "maybe"}),
    ("채팅_세션_플래그_오류", {"chat_pc_session_enabled": "maybe"}),
    ("B14_주소_없음", {"runtime_mode": "b14"}),
    ("B14_주소_형식_오류", {"b14_base_url": "ftp://example.test"}),
    ("업스트림_모드_오류", {"b14_upstream_mode": "nope"}),
    ("업스트림_HTTPS_주소_없음", {"b14_upstream_mode": "https"}),
    (
        "업스트림_충돌",
        {
            "b14_base_url": "https://a.example.test",
            "b14_upstream_mode": "https",
            "b14_upstream_url": "https://b.example.test",
        },
    ),
    ("B66_따옴표_HTTP", {"b66_quote_base_url": "http://quote.example.test"}),
    ("B66_따옴표_경로", {"b66_quote_base_url": "https://quote.example.test/path"}),
    ("타임아웃_숫자_아님", {"timeout_seconds": "abc"}),
    ("타임아웃_하한", {"timeout_seconds": 0}),
    ("타임아웃_상한", {"timeout_seconds": 3601}),
    ("완료_타임아웃_하한", {"completed_timeout_seconds": 0}),
    ("라이브_오류", {"live_enabled": "maybe"}),
    ("웹_제공자_오류", {"web_provider": "nope"}),
    ("웹_Firecrawl_키_없음", {"web_provider": "firecrawl"}),
    ("웹_Daum_키_없음", {"web_provider": "daum"}),
    ("웹_TinyFish_키_없음", {"web_provider": "tinyfish"}),
    ("웹_타임아웃_상한", {"web_timeout_seconds": 61}),
    ("인증_모드_오류", {"auth_mode": "nope"}),
    ("인증_공개_주소_없음", {"auth_mode": "password"}),
    (
        "인증_비밀_짧음",
        {
            "auth_mode": "password",
            "public_base_url": "https://chat.example.test",
            "session_secret": "short",
        },
    ),
    (
        "구글_클라이언트_없음",
        {
            "auth_mode": "google",
            "public_base_url": "https://chat.example.test",
            "session_secret": _fake_secret("s"),
        },
    ),
    (
        "구글_비밀_없음",
        {
            "auth_mode": "google",
            "public_base_url": "https://chat.example.test",
            "session_secret": _fake_secret("s"),
            "google_client_id": "fake-google-client-id",
        },
    ),
    ("사용자_키_짧음", {"custom_key_secret": "short"}),
    ("이전_키_짧음", {"custom_key_previous_secrets": "short"}),
    ("세션_수명_하한", {"session_max_age_seconds": 100}),
    ("쿠키_보안_오류", {"cookie_secure": "maybe"}),
    ("쿼터_소금_짧음", {"quota_salt": "short"}),
    ("익명_버스트_0", {"anonymous_burst_limit": "0"}),
    ("전역_한도_상한", {"global_daily_limit": "10000001"}),
    ("변환_등급_오류", {"conversion_daily_limits": {"nope": 1}}),
    ("변환_범위_오류", {"conversion_daily_limits": {"free": 0}}),
    ("변환_페이지_None_불가", {"conversion_daily_limits": {"free": None}}),
    ("추가_주소_HTTP", {"public_base_urls": "http://evil.example.test"}),
    ("파일_레인_형식_오류", {"file_lane_origin": "http://files.example.test"}),
    ("파일_레인_비밀_짧음", {"file_lane_ticket_secret": "short"}),
    ("BYOK_오류", {"byok_via_b14": "maybe"}),
    ("피드백_한도_0", {"feedback_daily_limit": "0"}),
    ("삭제_주소_HTTP", {"lovetree_account_delete_url": "http://delete.example.test"}),
    ("삭제_비밀_짧음", {"account_delete_rpc_secret": "short"}),
    ("이메일_로그인_오류", {"email_login_via_shared": "maybe"}),
    ("세션_행_검사_오류", {"session_user_row_check": "maybe"}),
    ("토큰_수명_0", {"mcp_pat_ttl_days": "0"}),
    ("로컬_검증_오류", {"local_verify_enabled": "maybe"}),
    ("이메일_복구_오류", {"email_recovery_enabled": "maybe"}),
    ("커넥터_그림자_오류", {"connector_account_shadow_enabled": "maybe"}),
    ("커넥터_키_오류", {"connector_account_key_enabled": "maybe"}),
]


def test_from_values_table_is_identical_to_golden() -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    rows = [_run_case(name, kwargs) for name, kwargs in CASES]
    assert rows == golden["cases"]


def test_from_env_reads_same_env_names_in_same_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    access: list[str] = []
    real_getenv = os.getenv

    def fake_getenv(key: str, default: object = None) -> object:
        access.append(key)
        return default

    monkeypatch.setattr(os, "getenv", fake_getenv)
    # from_env 내부의 resolve_b14_upstream은 넘긴 매핑만 읽는다(os.environ 직접
    # 접근 없음). 그래도 실제 os.getenv를 가짜로 바꾸면 순서가 남는다.
    settings = Settings.from_env()
    assert real_getenv is not None
    assert {"access_order": access, "fields": _settings_table(settings)} == golden["from_env"]
