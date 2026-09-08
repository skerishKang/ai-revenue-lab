from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.app_factory import create_app
from app.config import Settings


@pytest.fixture
def client() -> TestClient:
    settings = Settings.from_values(
        runtime_mode="mock",
        live_enabled="false",
        auth_mode="off",
    )
    app = create_app(settings=settings)
    return TestClient(app)


def test_kagent_dependency_available() -> None:
    import pathlib
    import kagent
    from app.main import app as main_app

    assert main_app is not None
    assert hasattr(kagent, "__file__") and kagent.__file__ is not None
    kagent_path = pathlib.Path(kagent.__file__).resolve()
    assert "kagent" in str(kagent_path)


def test_claw_manual_intake_preview_success_quote(client: TestClient) -> None:
    payload = {
        "content": "가상 테스트: A업체가 9월 말까지 샘플 20개 견적서를 요청함.",
        "channel": "kakao",
        "action": "quote",
        "sender_hint": "A업체",
    }
    resp = client.post("/api/claw/manual-intake/preview", json=payload)
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "no-store, max-age=0"
    data = resp.json()
    assert data["ok"] is True
    preview = data["preview"]
    assert "A업체" in preview["title"]
    assert "견적서 초안" in preview["title"]
    assert "가상 테스트" in preview["result_text"]
    assert preview["channel"] == "kakao"
    assert preview["action"] == "quote_draft"
    assert preview["connector_required"] is False
    assert preview["direct_kakao_send"] is False
    assert preview["direct_sms_send"] is False
    assert len(preview["disabled_actions"]) > 0


def test_claw_manual_intake_preview_all_actions(client: TestClient) -> None:
    actions = [
        ("quote", "견적서"),
        ("order", "발주서"),
        ("reply", "답장"),
        ("summary", "요청 사항 요약"),
    ]
    for act_key, expected_word in actions:
        payload = {
            "content": "업무 관련 테스트 본문 내용입니다.",
            "channel": "email",
            "action": act_key,
            "sender_hint": "B고객",
        }
        resp = client.post("/api/claw/manual-intake/preview", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert expected_word in data["preview"]["title"] or expected_word in data["preview"]["result_text"]


def test_claw_manual_intake_preview_requires_json(client: TestClient) -> None:
    resp = client.post(
        "/api/claw/manual-intake/preview",
        content="not json",
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 415
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "unsupported_media_type"


def test_claw_manual_intake_preview_empty_content_rejected(client: TestClient) -> None:
    payload = {
        "content": "   ",
        "channel": "sms",
        "action": "order",
    }
    resp = client.post("/api/claw/manual-intake/preview", json=payload)
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_content"


def test_claw_manual_intake_preview_oversized_content_rejected(client: TestClient) -> None:
    payload = {
        "content": "A" * 5000,
        "channel": "sms",
        "action": "order",
    }
    resp = client.post("/api/claw/manual-intake/preview", json=payload)
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "content_too_long"


def test_claw_manual_intake_preview_invalid_channel_rejected(client: TestClient) -> None:
    payload = {
        "content": "샘플 주문 요청",
        "channel": "unsupported_channel",
        "action": "order",
    }
    resp = client.post("/api/claw/manual-intake/preview", json=payload)
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_channel"


def test_claw_manual_intake_preview_invalid_action_rejected(client: TestClient) -> None:
    payload = {
        "content": "샘플 주문 요청",
        "channel": "kakao",
        "action": "forbidden_action",
    }
    resp = client.post("/api/claw/manual-intake/preview", json=payload)
    assert resp.status_code == 400
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "invalid_action"


def test_claw_manual_intake_preview_oversized_body_rejected(client: TestClient) -> None:
    big_str = "x" * 70_000
    resp = client.post(
        "/api/claw/manual-intake/preview",
        content=f'{{"content": "{big_str}"}}',
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code in (400, 413)
    data = resp.json()
    assert data["ok"] is False


def test_claw_static_assets_preserve_disabled_controls_and_safe_dom_sinks() -> None:
    from pathlib import Path

    chat_dir = Path(__file__).resolve().parents[1]
    index_html = (chat_dir / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (chat_dir / "static" / "app.js").read_text(encoding="utf-8")

    # Disabled controls must remain disabled
    assert 'claw-disabled-control" disabled aria-disabled="true"' in index_html
    assert 'Markdown 다운로드' in index_html
    assert 'DOCX 다운로드' in index_html
    assert '메모리 저장 후보' in index_html
    assert '이메일 발송' in index_html
    assert '공유 링크' in index_html

    # Endpoint must be wired in app.js
    assert "/api/claw/manual-intake/preview" in app_js

    # Preview must use textContent only
    assert "clawResultPreview.textContent =" in app_js
    assert "clawResultPreview.innerHTML" not in app_js

    # Browser persistence primitives forbidden
    forbidden_tokens = [
        "localStorage",
        "sessionStorage",
        "indexedDB",
        "cookieStore",
        "caches.open",
    ]
    for token in forbidden_tokens:
        assert token not in app_js

