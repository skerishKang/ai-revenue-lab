"""Temporary recorded scenarios for tutorial videos 05 and 07.

05 주의: ``test_tutorial_account_deletion_flow``는 실행할 때마다 시험 계정 B를
실제로 삭제한다. 다시 돌리려면 계정 B(kimbs5993+tutorial02@gmail.com)를 같은
별칭으로 재가입하고 ``PADIEM_LIVE_STORAGE_STATE`` 저장 상태를 먼저 갱신해야 한다.
"""
from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live


def _email(key: str) -> str:
    value = os.getenv(key, "").strip()
    if not value:
        pytest.skip("test_account_missing")
    return value


@pytest.mark.live_storage
def test_tutorial_account_deletion_flow(live_storage_state, live_scenario, live_base_url):
    page = live_scenario.page

    def open_settings():
        response = page.goto(f"{live_base_url}/", wait_until="domcontentloaded", timeout=60_000)
        assert response.status == 200, f"chat home returned HTTP {response.status}"
        page.locator("#accountProfileButton").wait_for(state="visible", timeout=30_000)
        page.locator("#accountProfileButton").click()
        page.locator("#settingsDialog[open]").wait_for(state="visible", timeout=30_000)
        page.locator("#accountDeleteOpen").wait_for(state="visible", timeout=30_000)
        return response

    live_scenario.step("open-account-settings", "계정 설정에서 탈퇴 안내를 확인해요.", open_settings)

    def open_delete_confirm():
        page.locator("#accountDeleteOpen").click()
        page.locator("#accountDeleteConfirmEmail").wait_for(state="visible", timeout=30_000)
        page.locator("#accountDeleteConfirmEmail").fill(_email("PADIEM_TUTORIAL02_EMAIL"))
        page.wait_for_function(
            "() => document.querySelector('#accountDeleteButton')?.disabled === false",
            timeout=30_000,
        )

    live_scenario.step("open-delete-confirm", "삭제 전에 안내 내용을 꼼꼼히 읽어요.", open_delete_confirm)

    def delete_account():
        page.locator("#accountDeleteButton").click()
        page.wait_for_function(
            "() => document.querySelector('#accountDeleteError')?.hidden !== false"
            " && document.querySelector('#passwordLoginIdentifier')?.offsetParent !== null",
            timeout=60_000,
        )
        return {"status_code": 200}

    live_scenario.step("delete-account", "탈퇴를 실행해요.", delete_account)


@pytest.mark.live_storage
def test_tutorial_external_ai_connect_flow(live_storage_state, live_scenario, live_base_url):
    page = live_scenario.page

    def open_settings():
        response = page.goto(f"{live_base_url}/", wait_until="domcontentloaded", timeout=60_000)
        assert response.status == 200, f"chat home returned HTTP {response.status}"
        page.locator("#accountProfileButton").wait_for(state="visible", timeout=30_000)
        page.locator("#accountProfileButton").click()
        page.locator("#settingsDialog[open]").wait_for(state="visible", timeout=30_000)
        page.locator("#mcpGatewaySettings").wait_for(state="visible", timeout=30_000)
        page.locator("#mcpGatewayEndpoint").wait_for(state="visible", timeout=30_000)
        return response

    live_scenario.step("open-connect-settings", "쓰던 AI 앱에 이 채팅의 연결 주소를 넣어요.", open_settings)

    def open_guide():
        response = page.goto(f"{live_base_url}/help.html#external-ai", wait_until="domcontentloaded", timeout=60_000)
        assert response.status == 200, f"help guide returned HTTP {response.status}"
        assert "외부 AI에 연결하기" in page.locator("body").inner_text()
        return response

    live_scenario.step("open-connection-guide", "로그인하면 승인 화면에서 범위와 PC를 확인해요.", open_guide)
