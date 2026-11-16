"""#7835 — '고침 알림 확인' 단추: 고침 + 미확인에서만 살아 있고, 누르면 서버에 남는다.

세 겹으로 확인한다.
1. 서버: 같은 사람의 고침 의견만 확인으로 기록되고, 다시 읽어도 그대로다.
2. 화면: 확인 전에는 단추가 살아 있고, 누르면 '확인함'으로 바뀌며, 다시 열어도 그대로다.
3. 회귀: 목록 요청이 응답을 주지 않아도 패널이 '불러오는 중'에 갇히지 않는다(#7835 원인).
"""
import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.feedback_routes import feedback, feedback_read
from test_7680_feedback_routes import OTHER, OWNER, payload, request
from test_7680_feedback_store import BODY, database

STATIC = Path(__file__).resolve().parents[1] / "static"
HARNESS = Path(__file__).with_name("chat_feedback_harness.js")
MODULE_JS = STATIC / "chat-feedback-module.js"
LOCALE_JS = STATIC / "locale.js"

SCENARIOS = [
    "fixed_ack_button_lifecycle",
    "read_state_survives_a_reload_and_other_statuses_have_no_button",
    "a_stalled_list_request_does_not_freeze_the_panel",
]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_ack_button_contract(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node is required for feedback DOM contracts")
    result = subprocess.run([node, str(HARNESS), str(STATIC), scenario], capture_output=True,
                            text=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"passed": scenario}


def test_only_the_owner_records_the_confirmation_and_it_survives_a_reload():
    async def scenario():
        db, store = database()
        try:
            created = payload(await feedback(request(store, method='POST', body={'body': BODY})))['feedback']
            feedback_id = created['id']
            await store.set_status(feedback_id, 'fixed')
            first = payload(await feedback(request(store)))
            assert first['unread_fixed_count'] == 1
            item = first['feedback'][0]
            assert item['status'] == 'fixed' and item['unread_fixed'] is True and item['fixed_version'] == 1

            # Someone else's id is not a record key: 404, and the owner stays unread.
            foreign = await feedback_read(request(store, method='POST', user=OTHER, feedback_id=feedback_id,
                                                  body={'fixed_version': item['fixed_version']}))
            assert foreign.status_code == 404
            assert payload(await feedback(request(store)))['unread_fixed_count'] == 1

            # A stale version writes nothing; the notice stays up.
            stale = await feedback_read(request(store, method='POST', feedback_id=feedback_id,
                                               body={'fixed_version': 0}))
            assert stale.status_code == 400

            read = await feedback_read(request(store, method='POST', feedback_id=feedback_id,
                                              body={'fixed_version': item['fixed_version']}))
            assert read.status_code == 200
            assert payload(read)['feedback']['unread_fixed'] is False

            # A fresh list is what a reload sees: still confirmed.
            reloaded = payload(await feedback(request(store)))
            assert reloaded['unread_fixed_count'] == 0
            assert reloaded['feedback'][0]['unread_fixed'] is False

            # A second fix is a new notice, and it can be confirmed once more.
            await store.set_status(feedback_id, 'reviewing')
            await store.set_status(feedback_id, 'fixed')
            second = payload(await feedback(request(store)))
            assert second['unread_fixed_count'] == 1
            version = second['feedback'][0]['fixed_version']
            assert version == 2
            again = await feedback_read(request(store, method='POST', feedback_id=feedback_id,
                                               body={'fixed_version': version}))
            assert again.status_code == 200
            assert payload(await feedback(request(store)))['unread_fixed_count'] == 0
        finally:
            db.close()
    asyncio.run(scenario())


def test_an_unfixed_item_has_nothing_to_confirm():
    async def scenario():
        db, store = database()
        try:
            created = payload(await feedback(request(store, method='POST', body={'body': BODY})))['feedback']
            for status in ('new', 'reviewing', 'deferred'):
                await store.set_status(created['id'], status)
                reply = await feedback_read(request(store, method='POST', feedback_id=created['id'],
                                                   body={'fixed_version': 1}))
                # The owner check passes, nothing is written, and the row keeps its state:
                # only a 'fixed' row can be confirmed, and the list still says so.
                assert reply.status_code == 200
                assert payload(reply)['feedback']['status'] == status
                assert payload(reply)['feedback']['unread_fixed'] is False
                row = payload(await feedback(request(store)))
                assert row['unread_fixed_count'] == 0
                assert row['feedback'][0]['unread_fixed'] is False
        finally:
            db.close()
    asyncio.run(scenario())


def test_the_module_never_leaves_the_panel_loading_after_a_lost_reply():
    js = MODULE_JS.read_text(encoding="utf-8")
    # A silent connection is bounded, and the loading flag is cleared before any
    # early return — otherwise one lost reply disables the button for good.
    assert "const REQUEST_TIMEOUT_MS = 15000;" in js
    assert "const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);" in js
    assert "finally { clearTimeout(timer);" in js
    load = js[js.index("async function load("):js.index("async function submit(")]
    assert load.index("state[loading] = false;") < load.index("if (!reply)")
    acknowledge = js[js.index("async function acknowledge("):js.index("function show(")]
    assert acknowledge.index("state.busy = false;") < acknowledge.index("if (!reply)")


def test_the_button_is_bound_to_fixed_and_says_when_it_is_done():
    js = MODULE_JS.read_text(encoding="utf-8")
    assert 'if (item.status === "fixed") {' in js
    assert 'button(item.unread_fixed ? "acknowledge" : "acknowledged", () => void acknowledge(item))' in js
    assert "read.disabled = !item.unread_fixed || state.busy || state.ownLoading;" in js
    assert 'read.setAttribute("aria-disabled", String(read.disabled));' in js
    locale = LOCALE_JS.read_text(encoding="utf-8")
    assert '"feedback-acknowledged": "확인함"' in locale
    assert '"feedback-acknowledged": "Read"' in locale
