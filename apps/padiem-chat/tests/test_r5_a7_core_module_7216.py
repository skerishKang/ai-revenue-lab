"""#7216 R5 A7 (core) — 공용 도우미·문구·파일 읽기 모듈 계약.

app.js의 공용 도우미·문구·파일 판정 14함수가 chat-core-module.js로
이동했고, app.js는 한 줄 전달 함수와 deps getter만 유지한다.
이 시험은 index 로드 순서, 전달 함수, deps 계약과 node vm 직접 호출을 검사한다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from _r5_b6_wiring import context_names, create_receives_app_context

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = (STATIC / "app.js").read_text(encoding="utf-8")
MODULE = (STATIC / "chat-core-module.js").read_text(encoding="utf-8")
INDEX = (STATIC / "index.html").read_text(encoding="utf-8")

NAMES = (
    "uiT",
    "idleNote",
    "setNote",
    "hwpLegacyGuidance",
    "formatClockTime",
    "formatBytes",
    "extensionOf",
    "documentMediaType",
    "readAsText",
    "readDocumentFile",
    "selectImage",
    "mappedUiError",
    "clawT",
    "localeOr",
)

EXPECTED_GETTERS = {
    "activeProject",
    "attachmentCopy",
    "runtimeNote",
    "ALLOWED_DOCUMENT_TYPES",
    "DOCUMENT_EXTENSION_TYPES",
    "ALLOWED_IMAGE_TYPES",
    "clawFallbackCopy",
}
EXPECTED_SETTERS: set[str] = set()

MOVED_MARKERS = (
    "window.PadiemChatCoreModule = {",
    "const lower = String(name || \"\").toLowerCase();",
    "if (bytes < 1024) return `${bytes} B`;",
    "return `${String(date.getHours()).padStart(2, \"0\")}:${String(date.getMinutes()).padStart(2, \"0\")}`;",
    "return uiT(\"hwp-legacy-guidance\") + \"\\n\" + uiT(\"hwp-legacy-steps\");",
)


def test_index_loads_core_module_before_app() -> None:
    assert INDEX.count("./chat-core-module.js") == 1
    assert INDEX.index("./chat-core-module.js") < INDEX.index("./app.js")
    assert INDEX.index("./chat-android-handoff-module.js") < INDEX.index(
        "./chat-core-module.js"
    )


def test_app_keeps_forwarders_and_factory() -> None:
    # R5 B7: core 모듈이 등록부(app.provide("core"))로 도달한다. app.js에
    # 전달 함수 정의가 없고, 모듈 조각에 이름이 있으며, 원래 팩토리 위치에서
    # 등록된다(실행 순서 불변).
    assert 'app.provide("core", window.PadiemChatCoreModule.create(' in APP
    for name in NAMES:
        assert f"function {name}(" not in APP, f"Forwarder should be removed: {name}"
        assert f"{name}," in MODULE, f"Missing from module: {name}"
    assert "function coreModule() {" in APP
    assert "window.PadiemChatCoreModule.create(Object.setPrototypeOf({" in APP


def test_core_apis_are_reachable_through_the_registry() -> None:
    """B7 보강: 등록부(app.provide("core"))로 14개 이름을 조회한다."""
    import json

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    script = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const staticDir = process.argv[1];
const fakeEl = () => ({
  hidden: true, textContent: "", dataset: {}, children: [],
  classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
  addEventListener() {}, removeEventListener() {},
  setAttribute() {}, getAttribute() { return null; },
  appendChild(c) { this.children.push(c); return c; }, append() {}, removeChild() {},
});
const byId = new Map();
const sandbox = {
  document: {
    getElementById: (id) => { if (!byId.has(id)) byId.set(id, fakeEl()); return byId.get(id); },
    querySelectorAll: () => [], querySelector: () => null,
    addEventListener() {}, removeEventListener() {},
    createElement: (tag) => ({ tag, textContent: "", className: "", dataset: {}, appendChild() {}, append() {}, setAttribute() {} }),
  },
  location: { search: "", hash: "", pathname: "/", href: "https://example.test/" },
  fetch: () => new Promise(() => {}),
  console: { error() {} },
  setTimeout,
};
sandbox.window = { ...sandbox };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(staticDir + "/chat-app-context.js", "utf8"), sandbox,
  { filename: "chat-app-context.js" });
vm.runInContext(fs.readFileSync(staticDir + "/chat-core-module.js", "utf8"), sandbox,
  { filename: "chat-core-module.js" });
const names = %s;
const result = vm.runInContext(`
  const app = window.PadiemChatAppContext.create({});
  app.provide("core", window.PadiemChatCoreModule.create(app));
  const out = {};
  for (const n of ${JSON.stringify(names)}) out[n] = typeof app[n];
  out;
`, sandbox, { filename: "registry-lookup" });
for (const n of names) {
  assert.equal(result[n], "function", n + " must be reachable through the registry");
}
console.log("REGISTRY_OK");
"""
    completed = subprocess.run(
        [node, "-e", script.replace("%s", json.dumps(list(NAMES))), str(STATIC)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "REGISTRY_OK" in completed.stdout


def test_moved_bodies_live_only_in_the_module_and_module_stays_under_500_lines() -> None:
    for marker in MOVED_MARKERS:
        assert marker in MODULE, marker
        assert marker not in APP, marker
    for name in NAMES:
        assert MODULE.count(f"function {name}(") == 1, name
    assert len(MODULE.splitlines()) <= 500


def test_deps_getters_and_setters_match_the_exact_closure_surface() -> None:
    block = create_receives_app_context(APP, "window.PadiemChatCoreModule")
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(value\)", block))
    assert gets <= EXPECTED_GETTERS
    assert gets | (EXPECTED_GETTERS & context_names(APP)) == EXPECTED_GETTERS
    assert sets <= EXPECTED_SETTERS
    assert sets | (EXPECTED_SETTERS & context_names(APP)) == EXPECTED_SETTERS


def test_core_module_runs_in_node_vm() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")

    script = r"""
(async () => {
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticDir = process.argv[1];
const strictSrc = fs.readFileSync(path.join(staticDir, "..", "tests", "_r5_strict_deps.js"), "utf8");
const modSrc = fs.readFileSync(path.join(staticDir, "chat-core-module.js"), "utf8");

const runtimeNote = { textContent: "", dataset: {} };
const activeProject = { name: "TestProj" };
const attachmentCopy = () => ({ idleNote: "idle note", unsupportedFormat: "unsupported" });
const ALLOWED_DOCUMENT_TYPES = new Set(["application/pdf", "text/plain"]);
const DOCUMENT_EXTENSION_TYPES = new Map([[".pdf", "application/pdf"], [".txt", "text/plain"]]);
const ALLOWED_IMAGE_TYPES = new Set(["image/png", "image/jpeg"]);
const clawFallbackCopy = {
  "claw-status-ok": "Status OK",
  "claw-hello": "Hello {name}!",
};

let depsAccessedAtCreate = false;
const rawDeps = {
  get runtimeNote() { return runtimeNote; },
  get activeProject() { return activeProject; },
  get attachmentCopy() { return attachmentCopy; },
  get ALLOWED_DOCUMENT_TYPES() { return ALLOWED_DOCUMENT_TYPES; },
  get DOCUMENT_EXTENSION_TYPES() { return DOCUMENT_EXTENSION_TYPES; },
  get ALLOWED_IMAGE_TYPES() { return ALLOWED_IMAGE_TYPES; },
  get clawFallbackCopy() { return clawFallbackCopy; },
};

const context = {
  window: {},
  document: {},
  console,
  setTimeout,
  clearTimeout,
  Date,
  Error,
  String,
  Math,
  Number,
  Object,
  URL: { createObjectURL: () => "blob:mock" },
};
vm.createContext(context);
vm.runInContext(strictSrc, context);
vm.runInContext(modSrc, context);

assert(context.window.PadiemChatCoreModule, "module must register on window");

// 1. Verify create() does not evaluate deps properties at initialization time
const probeDeps = new Proxy({}, {
  get(o, k) { depsAccessedAtCreate = true; throw new Error("deps." + String(k) + " accessed at create"); },
  set(o, k, v) { depsAccessedAtCreate = true; throw new Error("deps." + String(k) + " written at create"); },
});
const probeMod = context.window.PadiemChatCoreModule.create(probeDeps);
assert.equal(depsAccessedAtCreate, false, "create() must not touch deps at call time");

// 2. Strict deps execution
const strictDeps = context.r5StrictDeps(rawDeps, "coreDeps");
const mod = context.window.PadiemChatCoreModule.create(strictDeps);

// uiT
assert.equal(mod.uiT("test-key"), "test-key");
context.window.__padiemLocale = { text: (k, vars) => (k === "hello" ? `Hi ${vars?.who || ""}` : k) };
assert.equal(mod.uiT("hello", { who: "World" }), "Hi World");
assert.equal(mod.uiT("unknown"), "unknown");

// idleNote
assert.equal(mod.idleNote(), "active-project-note");

// setNote
mod.setNote("hello note", "warn");
assert.equal(runtimeNote.textContent, "hello note");
assert.equal(runtimeNote.dataset.state, "warn");

// hwpLegacyGuidance
assert(mod.hwpLegacyGuidance().includes("hwp-legacy-guidance"));

// formatClockTime
const fixedDate = new Date(2026, 10, 13, 9, 5);
assert.equal(mod.formatClockTime(fixedDate), "09:05");

// formatBytes
assert.equal(mod.formatBytes(500), "500 B");
assert.equal(mod.formatBytes(2048), "2 KB");
assert.equal(mod.formatBytes(2 * 1024 * 1024), "2.0 MB");

// extensionOf
assert.equal(mod.extensionOf("file.TXT"), ".txt");
assert.equal(mod.extensionOf("noext"), "");

// documentMediaType
assert.equal(mod.documentMediaType({ type: "application/pdf", name: "doc.pdf" }), "application/pdf");
assert.equal(mod.documentMediaType({ type: "other", name: "doc.txt" }), "text/plain");
assert.equal(mod.documentMediaType({ type: "other", name: "doc.xyz" }), null);

// mappedUiError
const err = mod.mappedUiError("failed", { error: { code: "invalid_param" } });
assert.equal(err.message, "failed");
assert.equal(err.uiMessageSafe, true);
assert.equal(err.code, "invalid_param");

// clawT
delete context.window.__padiemLocale;
assert.equal(mod.clawT("claw-status-ok"), "Status OK");
assert.equal(mod.clawT("claw-hello", { name: "Padiem" }), "Hello Padiem!");
assert.equal(mod.clawT("missing"), "Unable to update this Claw status. Please try again.");

// localeOr
assert.equal(mod.localeOr("key", "Default"), "Default");
context.window.__padiemLocale = { text: (k) => (k === "greeting" ? "안녕하세요" : k) };
assert.equal(mod.localeOr("greeting", "Default"), "안녕하세요");
assert.equal(mod.localeOr("other", "Default"), "Default");

// selectImage
const img = await mod.selectImage({ type: "image/png", name: "test.png", size: 100 });
assert.equal(img.type, "image");
assert.equal(img.mediaType, "image/png");

console.log("OK");
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
"""
    result = subprocess.run(
        [node, "-e", script, str(STATIC)],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, f"node vm error: {result.stderr}\nstdout: {result.stdout}"
    assert "OK" in result.stdout
