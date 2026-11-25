"""T2 Projects & project files — module ownership and direct behavior contract."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from _r5_b6_wiring import context_names, create_receives_app_context
from _r5_function_source import definition_source
from _support.r5_module_source_7216 import app_js, index_html

STATIC = Path(__file__).resolve().parents[1] / "static"
APP = app_js()
MODULE = definition_source("loadProjects")
INDEX = index_html()
STRICT = Path(__file__).with_name("_r5_strict_deps.js")
CONTEXT = STATIC / "chat-app-context.js"

FUNCTIONS = (
    "clearProjectsUI", "renderProjectState", "renderProjects", "setProjectsListNote",
    "loadMoreProjects", "loadProjects", "projectById", "ensureProject", "showProjectError",
    "fetchProjectFiles", "refreshActiveProjectFileCount", "renderProjectFiles",
    "loadProjectFilesForDialog", "projectBinaryMediaType", "setProjectFileBusy",
    "addProjectFile", "deleteProjectFile", "selectProject", "exitProject",
    "openProjectDialog", "closeProjectDialog", "saveProject", "deleteProject",
    "mountProjectControls", "wireProjectListeners", "openFile", "open",
)
DOM_IDS = (
    "projectsNavButton", "projectsBadge", "projectsSection", "projectsList", "projectsEmpty",
    "projectCreateButton", "projectBanner", "activeProjectName", "activeProjectFiles",
    "editProjectButton", "exitProjectButton", "projectDialog", "projectForm",
    "projectDialogTitle", "projectDialogClose", "projectDialogCancel", "projectNameInput",
    "projectInstructionsInput", "projectFormError", "projectSaveButton", "projectFilesPanel",
    "projectFileInput", "projectFilesList", "projectFilesUsage", "projectFilesEmpty",
    "projectFileStatus", "projectDrivePanel",
)
API_NAMES = FUNCTIONS + ("projectsBadge", "projectFileStatus", "editProjectButton", "exitProjectButton")
SHARED_STATE = ("projectsReady", "activeProject", "activeProjectFileCount")

_DOM_SETUP = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const modulePath = process.argv[1];
const strictPath = process.argv[2];
const byId = new Map();
const created = [];
const registrationLog = [];
const formActions = makeElement("div");

function makeElement(tag) {
  const el = {
    tagName: String(tag || "div").toUpperCase(),
    id: "", className: "", textContent: "", hidden: false, disabled: false,
    open: false, isConnected: true, value: "", files: [], dataset: {}, attrs: {},
    children: [], listeners: {}, focused: 0, scrolled: 0,
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
    removeAttribute(k) { delete this.attrs[k]; },
    addEventListener(type, fn) {
      (this.listeners[type] ??= []).push(fn);
      registrationLog.push(this.id + " " + type);
    },
    append(...xs) { this.children.push(...xs); },
    appendChild(x) { this.children.push(x); return x; },
    prepend(...xs) { this.children.unshift(...xs); },
    replaceChildren(...xs) { this.children = xs; },
    querySelector(selector) { return selector === ".project-form-actions" ? formActions : null; },
    querySelectorAll(selector) {
      if (selector !== ".project-item") return [];
      const out = [];
      const walk = (node) => {
        for (const child of node.children || []) {
          if (child.className.split(/\s+/).includes("project-item")) out.push(child);
          walk(child);
        }
      };
      walk(this);
      return out;
    },
    focus() { this.focused += 1; },
    scrollIntoView() { this.scrolled += 1; },
    showModal() { this.open = true; },
    close() { this.open = false; },
  };
  el.classList = {
    add(name) { if (!el.className.split(/\s+/).includes(name)) el.className = (el.className + " " + name).trim(); },
    remove(name) { el.className = el.className.split(/\s+/).filter((x) => x !== name).join(" "); },
    contains(name) { return el.className.split(/\s+/).includes(name); },
  };
  return el;
}

const documentStub = {
  getElementById(id) {
    if (!byId.has(id)) {
      const el = makeElement("div");
      el.id = id;
      byId.set(id, el);
    }
    return byId.get(id);
  },
  createElement(tag) { const el = makeElement(tag); created.push(el); return el; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  addEventListener() {}, removeEventListener() {},
};
const sandbox = {
  document: documentStub,
  console,
  setTimeout,
  requestAnimationFrame(fn) { fn(); return 1; },
};
sandbox.window = sandbox;
const window = sandbox;
sandbox.PadiemSharedTooltip = { label() {} };
sandbox.PadiemConfirmDialog = { confirm: async () => true };
sandbox.padiemProjectDriveFolder = { reset() {}, loadStatus() {} };
sandbox.PadiemProjectFileUpload = { upload: async () => ({ file: { id: "uploaded" } }) };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(strictPath, "utf8"), sandbox, { filename: "_r5_strict_deps.js" });
vm.runInContext(fs.readFileSync(modulePath, "utf8"), sandbox, { filename: "chat-project-module.js" });
assert.equal(Object.prototype.propertyIsEnumerable.call(window, "PadiemChatProjectModule"), false);
assert.equal(typeof window.PadiemChatProjectModule.create, "function");
"""


def _node(script: str, *args: Path) -> subprocess.CompletedProcess:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed in this runner")
    return subprocess.run(
        [node, "-e", script, *(str(arg) for arg in args)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )


def test_index_registration_and_app_owned_seams() -> None:
    assert INDEX.count("./chat-project-module.js") == 1
    assert INDEX.index("./chat-project-module.js") < INDEX.index("./app.js")
    assert 'app.provide("project",' in APP
    assert "window.PadiemChatProjectModule.create(Object.setPrototypeOf({" in APP
    assert APP.count("projectModule.mountProjectControls();") == 1
    assert APP.count("projectModule.wireProjectListeners();") == 1
    assert "window.PadiemChatProjectOpener = Object.freeze({" in APP
    assert "openFile: projectModule.openFile," in APP
    assert "open: projectModule.open," in APP


def test_project_declarations_functions_and_listeners_live_only_in_module() -> None:
    for element_id in DOM_IDS:
        marker = f'document.getElementById("{element_id}")'
        assert marker in MODULE, element_id
        assert marker not in APP, element_id
    assert 'projectDeleteButton.id = "projectDeleteButton";' in MODULE
    assert 'projectDeleteButton.id = "projectDeleteButton";' not in APP
    for marker in (
        "const PROJECT_BINARY_EXTENSION_MEDIA = new Map([",
        "let projectsNextCursor = null;",
        "let editingProjectId = null;",
        "let dialogProjectFiles = [];",
        "let highlightedProjectFileId = null;",
        "let projectFileBusy = false;",
    ):
        assert marker in MODULE, marker
        assert marker not in APP, marker
    for name in FUNCTIONS:
        assert MODULE.count(f"function {name}(") == 1, name
        assert f"function {name}(" not in APP, name
    for element_id in ("projectCreateButton", "editProjectButton", "exitProjectButton", "projectFileInput"):
        assert f'{element_id}.addEventListener("click"' in MODULE or f'{element_id}.addEventListener("change"' in MODULE
        assert f'{element_id}.addEventListener("click"' not in APP
        assert f'{element_id}.addEventListener("change"' not in APP
    assert len(MODULE.splitlines()) <= 1000


def test_shared_state_stays_app_owned_and_deps_surface_is_exact() -> None:
    block = create_receives_app_context(APP, "window.PadiemChatProjectModule")
    gets = set(re.findall(r"get (\w+)\(\)", block))
    sets = set(re.findall(r"set (\w+)\(\)", block))
    assert gets == {"binaryDocuments", "failureCodeNote", "fetch", "selectedAttachments"}
    assert sets == set()
    names = context_names(APP)
    for name in SHARED_STATE:
        assert f"let {name} =" in APP
        assert f"get {name}()" in APP
        assert f"set {name}(value)" in APP
        assert name in names
    assert "get loadProjects() { return projectModule.loadProjects; }" in APP
    assert "get renderProjectState() { return projectModule.renderProjectState; }" in APP


def test_create_wire_registry_and_listener_order_with_strict_empty_deps() -> None:
    script = _DOM_SETUP + r"""
vm.runInContext(fs.readFileSync(process.argv[3], "utf8"), sandbox, { filename: "chat-app-context.js" });
const app = window.PadiemChatAppContext.create({});
const empty = window.r5StrictDeps({}, "emptyCreateDeps");
const emptyModule = window.PadiemChatProjectModule.create(empty);
assert.equal(typeof emptyModule.loadProjects, "function");
const mod = window.PadiemChatProjectModule.create(window.r5StrictDeps({
  uiT(key) { return "T:" + key; },
}, "projectMountDeps"));
mod.mountProjectControls();
mod.wireProjectListeners();
app.provide("project", mod);
const expectedApi = __API_NAMES__;
assert.deepEqual(Object.keys(mod).sort(), expectedApi.slice().sort());
for (const name of expectedApi) {
  if (typeof mod[name] === "function") assert.equal(typeof app[name], "function", name);
  else assert.equal(app[name], mod[name], name);
}
assert.equal(created.length, 2);
const deleteButton = created[1];
assert.equal(deleteButton.id, "projectDeleteButton");
assert.equal(deleteButton.type, "button");
assert.equal(deleteButton.className, "project-danger");
assert.equal(deleteButton.hidden, true);
assert.equal(deleteButton.textContent, "T:project-delete");
assert.equal(deleteButton.getAttribute("aria-label"), "T:project-delete-aria");
assert.equal(formActions.children[0], deleteButton);
assert.deepEqual(registrationLog, [
  "projectsNavButton click", "projectCreateButton click", "editProjectButton click",
  "exitProjectButton click", "projectDialogClose click", "projectDialogCancel click",
  "projectForm submit", "projectDeleteButton click", "projectFileInput change",
  "projectDialog cancel",
]);
console.log("PROJECT_WIRING_OK");
"""
    result = _node(script.replace("__API_NAMES__", json.dumps(API_NAMES)), STATIC / "chat-project-module.js", STRICT, CONTEXT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROJECT_WIRING_OK" in result.stdout


_BEHAVIOR = _DOM_SETUP + r"""
const fetchCalls = [];
const resetCalls = [];
const notes = [];
const driveLoads = [];
const uploadCalls = [];
const readCalls = [];
const projects = [
  { id: "p1", name: "Project One", instructions: "first" },
  { id: "p2", name: "Project Two", instructions: "second" },
];
const filesByProject = {
  p1: [{ id: "f1", name: "one.txt", media_type: "text/plain", content_chars: 3 }],
  p2: [{ id: "f2", name: "two.txt", media_type: "text/plain", content_chars: 4 }],
};
sandbox.padiemProjectDriveFolder = {
  reset() {},
  loadStatus(id) { driveLoads.push(id); },
};
sandbox.PadiemProjectFileUpload = {
  async upload(options) { uploadCalls.push(options); return { file: { id: "uploaded" } }; },
};
async function fetchProject(url, init = {}) {
  const method = init.method || "GET";
  fetchCalls.push({ url, method, body: init.body });
  const ok = (body) => ({ ok: true, status: 200, json: async () => body });
  if (url === "/api/projects" && method === "GET") return ok({ projects, next_cursor: "next token" });
  if (url === "/api/projects?cursor=next%20token") {
    return ok({ projects: [{ id: "p3", name: "Project Three" }], next_cursor: null });
  }
  if (url === "/api/projects/missing") return { ok: false, status: 404, json: async () => ({}) };
  const fileMatch = /^\/api\/projects\/([^/]+)\/files(?:\/([^/]+))?$/.exec(url);
  if (fileMatch && method === "GET") return ok({ files: filesByProject[fileMatch[1]] || [] });
  if (fileMatch && method === "POST") {
    const payload = JSON.parse(init.body);
    const file = { id: "saved", name: payload.name, media_type: payload.media_type, content_chars: payload.text.length };
    filesByProject[fileMatch[1]] = [file];
    return ok({ file });
  }
  if (url === "/api/projects" && method === "POST") return ok({ project: { id: "p4", name: "Project Four" } });
  throw new Error("unexpected fetch " + method + " " + url);
}

let authState = { authenticated: true, history_ready: true, project_files_ready: true };
let authViewEpoch = 1;
let projectsReady = false;
let activeProject = null;
let activeProjectFileCount = 0;
let inFlight = false;
let selectedAttachments = [];
const input = documentStub.getElementById("messageInput");
const deps = window.r5StrictDeps({
  get authState() { return authState; },
  get authViewEpoch() { return authViewEpoch; },
  set authViewEpoch(value) { authViewEpoch = value; },
  get projectsReady() { return projectsReady; },
  set projectsReady(value) { projectsReady = value; },
  get activeProject() { return activeProject; },
  set activeProject(value) { activeProject = value; },
  get activeProjectFileCount() { return activeProjectFileCount; },
  set activeProjectFileCount(value) { activeProjectFileCount = value; },
  get inFlight() { return inFlight; },
  set inFlight(value) { inFlight = value; },
  get selectedAttachments() { return selectedAttachments; },
  get input() { return input; },
  get fetch() { return fetchProject; },
  get binaryDocuments() { return { headerFamily: async () => null, hwpxMedia: "application/hwp+zip" }; },
  get failureCodeNote() { return () => null; },
  uiT(key, params) { return key + (params && params.count !== undefined ? ":" + params.count : ""); },
  sidebarActionIcon() { return makeElement("span"); },
  setNote(value) { notes.push(value); },
  idleNote() { return "idle"; },
  resetConversationView(value) { resetCalls.push(value); },
  safeLocalUiMessage(_error, fallback) { return fallback; },
  mappedUiError(message) { return new Error(message); },
  extensionOf(name) { const m = /(\.[^.]+)$/.exec(String(name || "")); return m ? m[1].toLowerCase() : ""; },
  readDocumentFile: async (file) => { readCalls.push(file.name); return { name: file.name, mediaType: "text/plain", text: "text" }; },
  hwpLegacyGuidance() { return "legacy-hwp"; },
}, "projectLiveDeps");

(async () => {
  const mod = window.PadiemChatProjectModule.create(deps);
  mod.mountProjectControls();
  mod.wireProjectListeners();
  const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

  assert.equal(await mod.loadProjects(), true);
  assert.equal(projectsReady, true);
  assert.equal(documentStub.getElementById("projectsNavButton").disabled, false);
  const knownProject = mod.projectById("p1");
  assert.equal(knownProject && knownProject.name, "Project One", "projectById must return the loaded project");
  const beforeKnownLookup = fetchCalls.length;
  assert.equal((await mod.ensureProject("p1")).id, "p1");
  assert.equal(fetchCalls.length, beforeKnownLookup);
  assert.equal(mod.projectBinaryMediaType({ name: "a.PDF" }), "application/pdf");
  assert.equal(mod.projectBinaryMediaType({ name: "a.docx" }), "application/vnd.openxmlformats-officedocument.wordprocessingml.document");
  assert.equal(mod.projectBinaryMediaType({ name: "a.hwpx" }), "application/hwp+zip");
  assert.equal(mod.projectBinaryMediaType({ name: "a.txt" }), null);

  assert.equal(await mod.loadMoreProjects(), true);
  assert.equal(fetchCalls.some((call) => call.url === "/api/projects?cursor=next%20token"), true);
  assert.equal(mod.projectById("p3").name, "Project Three");

  assert.equal(mod.open("p1"), true);
  assert.equal(documentStub.getElementById("projectDialog").open, true);
  assert.equal(documentStub.getElementById("projectDrivePanel").hidden, false);
  assert.equal(driveLoads.at(-1), "p1");
  await mod.loadProjectFilesForDialog("p1");
  assert.equal(documentStub.getElementById("projectFilesList").children.length, 1);

  assert.equal(await mod.openFile("p1", "f1"), true);
  await mod.loadProjectFilesForDialog("p1");
  const selected = documentStub.getElementById("projectFilesList").children[0];
  assert.equal(selected.classList.contains("quick-selected-file"), true);
  assert.equal(selected.focused > 0, true);
  assert.equal(await mod.openFile("missing", "f1"), false);

  await mod.addProjectFile({ name: "note.txt" });
  const textPost = fetchCalls.find((call) => call.method === "POST" && call.url === "/api/projects/p1/files");
  assert.ok(textPost);
  assert.deepEqual(JSON.parse(textPost.body), { name: "note.txt", media_type: "text/plain", text: "text" });
  assert.deepEqual(readCalls, ["note.txt"]);
  assert.equal(documentStub.getElementById("projectFilesPanel").getAttribute("aria-busy"), null);
  assert.equal(documentStub.getElementById("projectFileStatus").hidden, true);

  await mod.addProjectFile({ name: "binary.pdf" });
  assert.equal(uploadCalls.length, 1);
  assert.equal(uploadCalls[0].projectId, "p1");
  assert.equal(uploadCalls[0].mediaType, "application/pdf");
  assert.deepEqual(readCalls, ["note.txt"]);

  mod.selectProject(projects[1]);
  await mod.refreshActiveProjectFileCount();
  assert.equal(activeProject.id, "p2");
  assert.equal(activeProjectFileCount, 1);
  assert.equal(resetCalls.at(-1), true);
  mod.exitProject();
  assert.equal(activeProject, null);
  assert.equal(activeProjectFileCount, 0);
  assert.equal(resetCalls.at(-1), false);

  mod.clearProjectsUI();
  assert.equal(projectsReady, false);
  assert.equal(activeProject, null);
  assert.equal(activeProjectFileCount, 0);
  assert.equal(documentStub.getElementById("projectsList").children.length, 0);
  assert.equal(documentStub.getElementById("projectsSection").hidden, false);
  assert.equal(documentStub.getElementById("projectsEmpty").hidden, false);
  assert.equal(documentStub.getElementById("projectsNavButton").disabled, true);
  console.log("PROJECT_BEHAVIOR_OK");
})().catch((error) => { console.error(error); process.exitCode = 1; });
"""


def test_moved_project_functions_execute_directly_with_strict_live_deps() -> None:
    result = _node(_BEHAVIOR, STATIC / "chat-project-module.js", STRICT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PROJECT_BEHAVIOR_OK" in result.stdout


def test_project_by_id_mutation_fails_the_direct_contract() -> None:
    original = "return projects.find((project) => project.id === id) || null;"
    assert MODULE.count(original) == 1
    mutated = MODULE.replace(original, "return null;")
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "chat-project-module.js"
        path.write_text(mutated, encoding="utf-8")
        result = _node(_BEHAVIOR, path, STRICT)
    assert result.returncode != 0
    assert "projectById" in result.stderr
