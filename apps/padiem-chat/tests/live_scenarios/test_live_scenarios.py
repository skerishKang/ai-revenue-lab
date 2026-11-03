"""Recorded browser scenarios. Unauthenticated cases use GET only."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytestmark = pytest.mark.live
BOOKAI_URL = "https://bookai.padiem.net"


def _assert_page_response(response, expected=200):
    assert response is not None, "navigation did not return an HTTP response"
    if response.status == 504:
        error = AssertionError("live request returned HTTP 504")
        error.status_code = 504
        raise error
    assert response.status == expected, f"expected HTTP {expected}, received {response.status}"
    return response


def _send_question(scenario, base_url: str, prompt: str):
    page = scenario.page
    page.locator("#messageInput").fill(prompt)
    with page.expect_response(
        lambda response: response.request.method == "POST"
        and urlsplit(response.url).path in {
            "/api/chat", "/api/chat/stream", "/api/orchestration"
        },
        timeout=120_000,
    ) as received:
        page.locator("#sendButton").click()
    response = received.value
    if response.status == 504:
        error = AssertionError("chat turn returned HTTP 504")
        error.status_code = response.status
        raise error
    assert response.status < 500, f"chat turn returned HTTP {response.status}"
    page.wait_for_function(
        "() => [...document.querySelectorAll('#messageList .assistant-message .assistant-content')]"
        ".some(node => (node.innerText || '').trim().length > 0)",
        timeout=120_000,
    )
    return response


def _assert_authenticated(page, base_url: str):
    response = page.request.get(f"{base_url}/api/auth/status", timeout=30_000)
    assert response.status == 200, f"auth status returned HTTP {response.status}"
    body = response.json()
    assert body.get("authenticated") is True, "provided session is not authenticated"
    return response


def test_guest_public_screens_and_read_only_auth_gate(live_scenario, live_base_url):
    page = live_scenario.page

    def home():
        response = page.goto(f"{live_base_url}/", wait_until="domcontentloaded", timeout=60_000)
        _assert_page_response(response)
        text = page.locator("body").inner_text()
        assert "안녕하세요." in text and "무엇을 도와드릴까요?" in text
        assert page.locator("#loginButton").count() == 1
        return response

    live_scenario.step("chat-first-screen", "첫 화면에서 무엇을 물어볼지 시작해요.", home)

    def help_page():
        response = page.goto(f"{live_base_url}/help.html", wait_until="domcontentloaded", timeout=60_000)
        _assert_page_response(response)
        text = page.locator("body").inner_text()
        assert "이렇게 말해 보세요" in text
        assert "모든 책에 적용합니다" in text
        assert "다른 기기에서 이어져요" in text
        return response

    live_scenario.step("help-bookai-copy", "로그인하면 다른 기기에서도 이어서 볼 수 있어요.", help_page)

    def install_page():
        response = page.goto(f"{live_base_url}/install.html", wait_until="domcontentloaded", timeout=60_000)
        _assert_page_response(response)
        text = page.locator("body").inner_text()
        assert "컴퓨터 연결 프로그램 설치 안내" in text
        assert "이 PC 연결하기" in text
        return response

    live_scenario.step("pc-install-guide", "내 컴퓨터를 연결할 설치 안내를 살펴봐요.", install_page)

    def auth_status():
        response = page.request.get(f"{live_base_url}/api/auth/status", timeout=30_000)
        assert response.status == 200, f"auth status returned HTTP {response.status}"
        body = response.json()
        assert body.get("authenticated") is False
        return response

    live_scenario.step("guest-auth-status", "게스트 상태를 확인해요.", auth_status)

    def conversations_requires_login():
        response = page.request.get(f"{live_base_url}/api/conversations", timeout=30_000)
        if response.status == 504:
            error = AssertionError("conversation gate returned HTTP 504")
            error.status_code = 504
            raise error
        assert response.status == 401, f"guest conversation list returned HTTP {response.status}"
        body = response.json()
        error = body.get("error", {})
        assert error.get("code") == "unauthorized"
        assert "로그인이 필요합니다." in error.get("message", "")
        return response

    live_scenario.step(
        "guest-login-required-gate",
        "로그인이 필요한 항목은 로그인 안내로 안전하게 막아요.",
        conversations_requires_login,
    )

    def bookai_guest():
        response = page.goto(BOOKAI_URL, wait_until="domcontentloaded", timeout=60_000)
        _assert_page_response(response)
        assert page.locator("#openBook").is_visible()
        assert page.locator("#todayDataStatus").count() == 1
        return response

    live_scenario.step(
        "bookai-guest-device-storage",
        "북AI에서 읽기 기록을 남겨요.",
        bookai_guest,
    )


@pytest.mark.live_storage
def test_first_question_with_prepared_login(live_storage_state, live_scenario, live_base_url):
    page = live_scenario.page

    def open_chat():
        response = page.goto(f"{live_base_url}/", wait_until="domcontentloaded", timeout=60_000)
        _assert_page_response(response)
        return response

    live_scenario.step("open-chat-with-session", "준비된 계정으로 Chat을 열어요.", open_chat)
    live_scenario.step(
        "verify-login-session",
        "로그인 상태를 확인해요.",
        lambda: _assert_authenticated(page, live_base_url),
    )
    live_scenario.step(
        "send-first-question",
        "궁금한 점을 질문으로 보내요.",
        lambda: _send_question(live_scenario, live_base_url, "안녕하세요. 간단히 인사해 주세요."),
    )


@pytest.mark.live_storage
def test_pc_install_guide_and_read_only_xlsx_search(live_storage_state, live_scenario, live_base_url):
    page = live_scenario.page

    def install_guide():
        response = page.goto(f"{live_base_url}/install.html", wait_until="domcontentloaded", timeout=60_000)
        _assert_page_response(response)
        assert "이 PC 연결하기" in page.locator("body").inner_text()
        return response

    live_scenario.step("pc-install-guide", "내 컴퓨터를 연결할 설치 안내를 살펴봐요.", install_guide)

    def connected_device_list():
        response = page.request.get(
            f"{live_base_url}/api/claw/local-access/devices", timeout=30_000
        )
        assert response.status == 200, f"device list returned HTTP {response.status}"
        payload = response.json()
        devices = payload.get("devices", []) if isinstance(payload, dict) else []
        assert devices, "a pre-approved test PC is required for this scenario"
        return response

    live_scenario.step(
        "verify-preapproved-pc",
        "준비된 시험 PC 연결을 확인해요.",
        connected_device_list,
    )

    def search_files():
        response = page.goto(f"{live_base_url}/", wait_until="domcontentloaded", timeout=60_000)
        _assert_page_response(response)
        return _send_question(live_scenario, live_base_url, "내 컴퓨터에서 xlsx 찾아줘")

    live_scenario.step("search-xlsx-on-pc", "자연어로 컴퓨터의 파일을 찾아봐요.", search_files)


@pytest.mark.live_storage
def test_synthetic_document_upload_summary_and_download(live_storage_state, live_scenario, live_base_url, tmp_path):
    page = live_scenario.page
    marker = "SCENARIO_SIM_SYNTHETIC_DOC_6724"
    synthetic = tmp_path / "scenario-simulation.txt"
    synthetic.write_text(
        f"{marker}\n합성 시험 문서입니다. 실제 개인정보는 없습니다.\n",
        encoding="utf-8",
    )

    def open_chat():
        response = page.goto(f"{live_base_url}/", wait_until="domcontentloaded", timeout=60_000)
        _assert_page_response(response)
        return response

    live_scenario.step("open-document-chat", "합성 문서를 대화에 첨부해요.", open_chat)

    def attach_document():
        page.locator("#attachmentFileInput").set_input_files(str(synthetic))
        page.locator("#attachmentChipList").get_by_text("scenario-simulation.txt").wait_for(
            state="visible", timeout=30_000
        )
        return {"status_code": 200}

    live_scenario.step("attach-synthetic-text", "합성 문서를 대화에 첨부해요.", attach_document)

    def summarize():
        page.locator("#messageInput").fill(
            f"첨부 문서를 요약하고 {marker} 문구를 포함해 주세요. 결과를 저장해 주세요."
        )
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and urlsplit(response.url).path in {
                "/api/chat", "/api/chat/stream", "/api/orchestration"
            },
            timeout=120_000,
        ) as received:
            page.locator("#sendButton").click()
        response = received.value
        if response.status == 504:
            error = AssertionError("document summary returned HTTP 504")
            error.status_code = response.status
            raise error
        assert response.status < 500, f"document summary returned HTTP {response.status}"
        page.wait_for_function(
            "() => [...document.querySelectorAll('#messageList .assistant-message .assistant-content')]"
            ".some(node => (node.innerText || '').includes('SCENARIO_SIM_SYNTHETIC_DOC_6724'))",
            timeout=120_000,
        )
        return response

    live_scenario.step("summarize-document", "문서에서 필요한 내용을 요약해요.", summarize)

    def download_saved_answer():
        page.locator("#messageList .assistant-message .answer-more").last.click()
        with page.expect_download(timeout=30_000) as downloaded:
            page.locator("#messageList .assistant-message .answer-download").last.click()
        artifact = downloaded.value
        assert artifact.suggested_filename
        return {"status_code": 200}

    live_scenario.step("download-saved-summary", "요약 결과를 파일로 내려받아요.", download_saved_answer)


def _open_today(page):
    page.evaluate("() => window.showScreen?.('library')")
    # Desktop keeps TODAY at opacity 0 until the shelf is hovered.
    page.locator("#library").hover()
    page.locator("#todayEntry").click()
    page.locator("#today").wait_for(state="visible", timeout=30_000)


def _bookai_authenticated(page) -> bool:
    page.wait_for_function("() => !!window.BookAISession", timeout=60_000)
    return bool(page.evaluate("() => window.BookAISession.refresh()"))


def _bookai_sync_or_fail(page) -> dict:
    synced = page.evaluate("() => window.BookAISync.syncNow()")
    assert synced.get("state") == "synced", f"BookAI account sync did not complete: {synced}"
    return synced


def _bookai_resume(page) -> dict:
    return page.evaluate(
        "() => { const best = window.storyMemoryContinueReadingStatus().best;"
        " return {locator: best.record.canonicalLocator, title: best.title, progress: best.progressText}; }"
    )


@pytest.mark.live_storage
def test_bookai_reading_screen_with_prepared_account(
    live_storage_state, live_scenario, live_base_url
):
    page = live_scenario.page

    def open_bookai():
        response = page.goto(BOOKAI_URL, wait_until="domcontentloaded", timeout=60_000)
        _assert_page_response(response)
        assert page.locator("#openBook").is_visible()
        assert page.locator("#todayDataStatus").count() == 1
        if not _bookai_authenticated(page):
            pytest.skip("test_account_missing")
        page.wait_for_function(
            "() => document.getElementById('todayCloudLabel')?.textContent === '로그인됨'",
            timeout=30_000,
        )
        return response

    live_scenario.step("bookai-with-session", "로그인한 북AI 화면을 열어요.", open_bookai)

    def open_reading():
        _open_today(page)
        page.locator("#todayContinueBtn").click()
        page.locator("#reader.active").wait_for(state="visible", timeout=30_000)
        page.wait_for_function(
            "() => { const best = window.storyMemoryContinueReadingStatus?.()?.best;"
            " return !!best && best.record.authoritative === true; }",
            timeout=30_000,
        )
        _bookai_sync_or_fail(page)
        return {"status_code": 200, "checkpoint": _bookai_resume(page)}

    checkpoint = live_scenario.step(
        "open-reading-screen",
        "읽은 위치와 기록을 이어서 남겨요.",
        open_reading,
    )["checkpoint"]

    second_context = live_scenario.open_second_context(live_storage_state)
    page2 = second_context.new_page()

    def resume_on_second_device():
        response = page2.goto(BOOKAI_URL, wait_until="domcontentloaded", timeout=60_000)
        _assert_page_response(response)
        assert _bookai_authenticated(page2), "second device did not inherit the account session"
        _bookai_sync_or_fail(page2)
        page2.wait_for_function(
            "(expected) => { const best = window.storyMemoryContinueReadingStatus?.()?.best;"
            " return !!best && best.record.canonicalLocator === expected; }",
            arg=checkpoint["locator"],
            timeout=60_000,
        )
        _open_today(page2)
        page2.wait_for_function(
            "() => document.getElementById('todayContinueBtn')?.dataset.exactResume === 'true'",
            timeout=30_000,
        )
        button = page2.locator("#todayContinueBtn")
        assert button.inner_text().strip() == "정확한 위치에서 이어 읽기 →"
        assert page2.locator("#todayContinueTitle").inner_text().strip() == checkpoint["title"]
        progress = page2.locator("#todayContinueProgressText").inner_text().strip()
        assert progress and progress != "읽기 전", f"unexpected second-device progress: {progress!r}"
        return {"status_code": 200}

    try:
        live_scenario.step(
            "resume-reading-on-second-device",
            "다른 기기에서 읽던 내용을 이어 봐요.",
            resume_on_second_device,
            page=page2,
        )
    finally:
        live_scenario.close_context(page2)


@pytest.mark.live
def test_account_deletion_remains_script_only():
    pytest.skip("account-deletion-scenario-not-active")
