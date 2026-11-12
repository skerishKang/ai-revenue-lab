"""#7216 R5 0단계 — 공용 함수 소스 도우미 계약 (R-01).

R-01: 시험 다수가 ``function 이름(`` 글자로 app.js를 잘라 함수 본문을 읽는다.
단계(A1~A10)마다 함수가 chat-*-module.js로 옮겨지므로, 시험은 이 도우미로
"app.js든 분리 모듈이든 같은 방법"으로 찾아야 한다. 이 계약은 도우미 자체를
고정한다: 실제 정의(한 줄 전달 함수 제외)의 파일·소스·위치·개수와, index.html
로드 순서를 따르는 결합 소스를 검사한다. 제품 코드는 읽기만 한다.
"""
from __future__ import annotations

import re

from _r5_function_source import (
    APP_JS,
    app_source,
    combined_source,
    definition_count,
    definition_file,
    definition_index,
    definition_source,
    function_body,
    module_files,
    module_sources,
)

# A1~A7에서 옮겨질 app.js 구역 함수(이동 전)와 이미 분리된 모듈 함수(이동 후).
APP_SIDE_NAMES = (
    "submitPrompt",
    "buildRetryBox",
)
MODULE_SIDE_NAMES = (
    "openClawAutomation",       # chat-automation-module.js (R5 A1)
    "loadClawAutomationRules",  # chat-automation-module.js (R5 A1)
    "renderClawRunCard",        # chat-run-history-module.js (R5 A2)
    "readClawRuns",             # chat-run-history-module.js (R5 A2)
    "syncApprovedMemoryVisibility",  # chat-memory-module.js (R5 A2)
    "openAuthDialog",       # chat-auth-module.js (R5 4단계)
    "closeSidebar",         # chat-sidebar-module.js (R5 1단계)
    "showConversation",     # chat-conversation-module.js (R5 5a)
    "requestAnswer",        # chat-streaming-module.js (R5 5b)
    "waitForAcceptedPcRun",   # chat-pc-run-module.js (R5 A3)
    "recoverStoredPcResult",  # chat-pc-run-module.js (R5 A3)
    "syncComposerForClaw",       # chat-claw-status-module.js (R5 A4)
    "clawVisibleExecutePayload", # chat-claw-status-module.js (R5 A4)
    "beginClawWait",             # chat-claw-status-module.js (R5 A4)
    "clearClawWait",             # chat-claw-status-module.js (R5 A4)
    "runClawExecution",          # chat-claw-run-module.js (R5 A5a)
    "readAsText",                # chat-core-module.js (R5 A7)
    "loadRecentConversations",  # chat-history-module.js (R5 3단계)
)

# app.js 안의 한 줄 전달 함수 모양: [async] function 이름(...a) { return xModule().이름(...a); }
_FORWARDER = re.compile(r"^\s*(?:async\s+)?function\s+\w+\s*\([^)]*\)\s*\{\s*return\s+\w+Module\(\)\.\w+\(")


def test_index_orders_modules_before_app_and_helper_follows_it() -> None:
    files = module_files()
    assert len(files) >= 7
    assert files[-1] != APP_JS
    index_text = (APP_JS.parent / "index.html").read_text(encoding="utf-8")
    app_pos = index_text.index('"./app.js"')
    for path in files:
        # R5 B1: 공유 컨텍스트(chat-app-context.js)는 -module.js 접미가 없다.
        assert path.name.endswith("-module.js") or path.name == "chat-app-context.js"
        assert index_text.index(f'"./{path.name}"') < app_pos


def test_app_side_functions_resolve_to_app_js_with_one_real_definition() -> None:
    for name in APP_SIDE_NAMES:
        assert definition_file(name) == APP_JS, name
        assert definition_count(name) == 1, name
        start = definition_index(name)
        assert re.match(r"(?:async\s+)?function\s+" + re.escape(name) + r"\(", app_source()[start:])


def test_module_side_functions_resolve_to_their_module_not_the_forwarder() -> None:
    for name in MODULE_SIDE_NAMES:
        path = definition_file(name)
        assert path != APP_JS, name
        assert definition_count(name) == 1, name
        source = definition_source(name)
        start = definition_index(name)
        assert re.match(r"(?:async\s+)?function\s+" + re.escape(name) + r"\(", source[start:])
        # app.js에 남은 것이 있다면 전달 함수뿐이다. B1 시범 구역(openClawAutomation,
        # loadClawAutomationRules)은 등록부로 바뀌어 app.js에 아무 흔적도 없다.
        app_hit = app_source().find(f"function {name}(")
        if app_hit != -1:
            assert _FORWARDER.match(app_source()[app_hit:]), name


def test_function_body_matches_the_long_standing_slice_rule() -> None:
    # 시험들이 쓰던 절단 규칙: 정의 시작부터 첫 "\n  }" 앞까지.
    for name in ("openClawAutomation", "openAuthDialog"):
        body = function_body(name)
        source = definition_source(name)
        start = source.index(f"function {name}(")
        assert body == source[start:source.index("\n  }", start)]
        assert "function " + name in body


def test_combined_source_keeps_load_order_modules_then_app() -> None:
    shipped = combined_source()
    app_text = app_source()
    assert shipped.endswith(app_text)
    parts = [text for _, text in module_sources()]
    assert len(parts) == len(module_files())
    pos = 0
    for text in parts:
        found = shipped.index(text, pos)
        assert found >= pos
        pos = found + len(text)
    # 결합 소스 안에서 실제 정의(모듈)가 전달 함수(app.js)보다 먼저 나온다 —
    # 이동 뒤에도 .index 계열이 전달 함수가 아니라 실제 본문을 먼저 가리킨다.
    module_def = definition_index("openAuthDialog")
    forwarder_in_app = len(shipped) - len(app_text) + app_text.index("function openAuthDialog(")
    assert module_def < forwarder_in_app
