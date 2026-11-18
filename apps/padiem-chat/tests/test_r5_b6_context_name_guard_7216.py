"""R5 B6 — 공유 문맥 이름 보호 계약 (중복 이름 방지).

B6 리뷰: 모듈 API가 공유 상태 접근자와 같은 이름을 내놓으면 접근자를 조용히
가리는 문제를 막는다. 접근자와 겹치는 이름은 원칙적으로 오류이고, 예외는
chat-app-context.js의 ACCESSOR_SHADOW_ALLOWLIST뿐이다 — 각 이름마다 "모듈 값을
읽어도 app.js 실제 상태와 어긋나지 않는 이유"가 주석으로 기록되어 있다.

이 시험은 (1) 목록 밖 이름이 접근자와 겹치면 오류를 내고 접근자가 살아 남는지,
(2) 목록 안 이름은 모듈 값이 보이는지, (3) 문맥이 직접 소유한 참조(공유 DOM,
provide)와의 겹침도 오류인지, (4) 기존 중복 등록·중복 이름 오류가 그대로인지
확인한다.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
CONTEXT = (STATIC / "chat-app-context.js").read_text(encoding="utf-8")

_HARNESS = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");

// create()는 공유 DOM 5개를 getElementById로 조회한다 — 최소 스텁.
const byId = new Map();
const fakeEl = () => ({ hidden: true, textContent: "", children: [] });
const document = {
  getElementById: (id) => { if (!byId.has(id)) byId.set(id, fakeEl()); return byId.get(id); },
};
const window = { document };

eval(fs.readFileSync(__CONTEXT_PATH__, "utf8"));

// app.js의 문맥 리터럴과 같은 모양: 접근자는 shared의 own property다.
// probeState는 목록 밖 대표 접근자, syncClawRunHistoryVisibility와
// closeSidebar는 ACCESSOR_SHADOW_ALLOWLIST의 이름이다.
const shared = {};
Object.defineProperty(shared, "probeState", {
  get() { return "app.js accessor value"; },
  set() {},
  enumerable: true, configurable: true,
});
Object.defineProperty(shared, "syncClawRunHistoryVisibility", {
  get() { return "app.js accessor value"; },
  set() {},
  enumerable: true, configurable: true,
});
Object.defineProperty(shared, "closeSidebar", {
  get() { return "app.js accessor value"; },
  set() {},
  enumerable: true, configurable: true,
});
Object.defineProperty(shared, "selectedProductTier", {
  get() { return "app.js accessor value"; },
  set() {},
  enumerable: true, configurable: true,
});
Object.defineProperty(shared, "closeSettings", {
  get() { return "app.js accessor value"; },
  set() {},
  enumerable: true, configurable: true,
});
Object.defineProperty(shared, "setNavActive", {
  get() { return "app.js accessor value"; },
  set() {},
  enumerable: true, configurable: true,
});
for (const k of ["setAuthFormError", "syncAuthDialogMethods", "openAuthDialog", "closeAuthDialog"]) {
  Object.defineProperty(shared, k, {
    get() { return "app.js accessor value"; },
    set() {},
    enumerable: true, configurable: true,
  });
}

const newApp = () => window.PadiemChatAppContext.create(shared);
const checks = {};

// (1) 모듈 이름 중복 등록은 여전히 오류(기존 계약 유지).
const app1 = newApp();
app1.provide("modA", {});
let threw = null;
try { app1.provide("modA", {}); } catch (e) { threw = e; }
assert.ok(threw && /duplicate module registration/.test(String(threw)), String(threw));
checks.duplicate_module_throws = true;

// (2) 서로 다른 모듈이 같은 이름을 내놓으면 여전히 오류(기존 계약 유지).
const app2 = newApp();
app2.provide("modA", { sharedName: 1 });
threw = null;
try { app2.provide("modB", { sharedName: 2 }); } catch (e) { threw = e; }
assert.ok(threw && /duplicate name/.test(String(threw)), String(threw));
checks.duplicate_name_throws = true;

// (3) 목록 밖 이름이 공유 접근자와 겹치면 오류(조용한 덮어쓰기 금지) —
// 오류 뒤에도 접근자는 그대로 살아 있어야 한다.
const app3 = newApp();
threw = null;
try { app3.provide("modC", { probeState: "module value" }); } catch (e) { threw = e; }
assert.ok(threw && /collides with a shared accessor/.test(String(threw)), String(threw));
assert.equal(app3.probeState, "app.js accessor value", "접근자가 살아 있다");
checks.outside_allowlist_throws = true;

// (4) 목록 안 이름은 모듈 값이 보인다(소유자 위임 — 근거는 allowlist 주석).
const app4 = newApp();
const owner = () => "run-history owner";
app4.provide("runHistory", { syncClawRunHistoryVisibility: owner });
assert.equal(app4.syncClawRunHistoryVisibility, owner, "모듈 값이 보인다");
const sidebarOwner = () => "sidebar owner";
app4.provide("sidebar", { closeSidebar: sidebarOwner });
assert.equal(app4.closeSidebar, sidebarOwner, "allowlist된 두 번째 이름도 모듈 값이 보인다");
const settingsOwner = () => "settings owner";
app4.provide("settings", { selectedProductTier: settingsOwner, closeSettings: settingsOwner });
assert.equal(app4.selectedProductTier, settingsOwner, "allowlist된 세 번째 이름도 모듈 값이 보인다");
assert.equal(app4.closeSettings, settingsOwner, "allowlist된 네 번째 이름도 모듈 값이 보인다");
const navOwner = () => "nav owner";
app4.provide("nav", { setNavActive: navOwner });
assert.equal(app4.setNavActive, navOwner, "allowlist된 다섯 번째 이름도 모듈 값이 보인다");
const dialogOwner = () => "login-dialog owner";
app4.provide("loginDialog", {
  setAuthFormError: dialogOwner, syncAuthDialogMethods: dialogOwner,
  openAuthDialog: dialogOwner, closeAuthDialog: dialogOwner,
});
for (const k of ["setAuthFormError", "syncAuthDialogMethods", "openAuthDialog", "closeAuthDialog"]) {
  assert.equal(app4[k], dialogOwner, "allowlist된 로그인 대화상자 이름도 모듈 값이 보인다: " + k);
}
checks.allowlisted_name_shows_module_value = true;

// (5) 문맥이 직접 소유한 참조(공유 DOM·provide)와 겹쳐도 오류.
const app5 = newApp();
threw = null;
try { app5.provide("modD", { clawRunHistory: {} }); } catch (e) { threw = e; }
assert.ok(threw && /collides with a context-owned ref/.test(String(threw)), String(threw));
threw = null;
try { app5.provide("modE", { provide: () => {} }); } catch (e) { threw = e; }
assert.ok(threw && /collides with a context-owned ref/.test(String(threw)), String(threw));
checks.context_owned_ref_throws = true;

console.log("RESULT_JSON " + JSON.stringify({ ok: true, checks }));
"""


def test_context_name_guard_in_node_vm() -> None:
    harness = _HARNESS.replace("__CONTEXT_PATH__", json.dumps(str(STATIC / "chat-app-context.js")))
    with tempfile.TemporaryDirectory() as directory:
        harness_path = Path(directory) / "b6_context_name_guard.cjs"
        harness_path.write_text(harness, encoding="utf-8")
        result = subprocess.run(["node", str(harness_path)], capture_output=True, text=True,
                                encoding="utf-8", timeout=60)
    lines = [l for l in result.stdout.splitlines() if l.startswith("RESULT_JSON ")]
    assert lines, f"harness produced no result: {result.stdout[-800:]} {result.stderr[-400:]}"
    payload = json.loads(lines[-1][len("RESULT_JSON "):])
    assert payload.get("ok") is True, payload
    assert set(payload["checks"]) == {
        "duplicate_module_throws", "duplicate_name_throws",
        "outside_allowlist_throws", "allowlisted_name_shows_module_value",
        "context_owned_ref_throws",
    }, payload["checks"]
