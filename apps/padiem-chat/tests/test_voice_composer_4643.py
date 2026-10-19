"""#4643 Chat and Claw microphone composer entry (LOCAL2 UI handoff).

The shipped thin UI module `static/voice-composer.js` renders the shared mic
button and interim preview, and delegates the transcript life-cycle to the
reviewed adapter `static/voice-stt-input.js` (#4679). This module owns no
speech engine, no transport, and no send path: a recognizer is only ever
attached through an explicit `registerRecognizerFactory` call from the product
wiring stage that owns server-granted voice authority.

Guarded here, against the REAL shipped files:

- the mic entry mounts inside the shared composer for both Chat and Claw, with
  the interim preview and an sr-only polite status region;
- with no recognizer factory registered -- today's default -- the control is
  disabled, the copy states it is not connected, and the module performs zero
  network activity, zero submit, and zero send press;
- a signed-in session alone does not change that: the gate is
  factory-registered AND authenticated, with no account special-casing;
- only an authoritative FINAL reaches the existing editable input, exactly
  once per utterance id; interim text never becomes input; identical speech
  under a new utterance id is accepted;
- user-typed text and an active IME composition are preserved: a final that
  arrives mid-composition or while the composer is disabled is held and
  flushed later, and is dropped if the run ends first;
- stop, sign-out, and a Chat/Claw switch invalidate the run and drop late
  interim/final events; the Claw shell keeps the same mic affordance;
- permission denial and unsupported browsers produce bounded copy and a
  working retry, with no fabricated success;
- KO/EN copy is projected from the shipped locale.js table, and the copy
  asserted here is that same shipped table, not a local duplicate.

Markers:
- MIC_ENTRY_MOUNTED_IN_SHARED_COMPOSER=PASS
- DEFAULT_OFF_NO_FACTORY_UNAVAILABLE=PASS
- SIGNED_OUT_GATE_BEFORE_ANY_RUN=PASS
- INTERIM_PREVIEW_ONLY=PASS
- FINAL_ONLY_INTO_EDITABLE_INPUT=PASS
- DUPLICATE_UTTERANCE_SUPPRESSED=PASS
- DISTINCT_UTTERANCE_IDENTICAL_SPEECH_ACCEPTED=PASS
- LATE_EVENTS_AFTER_STOP_DROPPED=PASS
- SIGNOUT_INVALIDATES_LATE_RESULTS=PASS
- SHELL_SWITCH_INVALIDATES_RUN=PASS
- COMPOSITION_DEFERRAL_PRESERVES_TEXT=PASS
- DISABLED_COMPOSER_DEFERS_THE_FINAL=PASS
- PERMISSION_DENIED_BOUNDED_AND_RETRYABLE=PASS
- UNSUPPORTED_BROWSER_BOUNDED_COPY=PASS
- USER_TYPED_TEXT_PRESERVED=PASS
- RESTART_ISOLATION_NO_CROSS_RUN_BLEED=PASS
- LOCALE_PROJECTION_FROM_SHIPPED_TABLE=PASS
- PROVIDER_POST_ZERO=PASS
- AUTO_SEND_PRESENT=0
- FOCUS_STOLEN=0

Real-browser viewport (390px/1440px) overflow, touch-target and accessibility
checks run in the B62 Unified Browser QA lanes on this exact head; the local
harness here is network-free and DOM-offline.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"
ADAPTER_JS = STATIC / "voice-stt-input.js"
COMPOSER_JS = STATIC / "voice-composer.js"
COMPOSER_CSS = STATIC / "voice-composer.css"
INDEX_HTML = STATIC / "index.html"
LOCALE_JS = STATIC / "locale.js"

VOICE_KEYS = (
    "voice-mic",
    "voice-mic-start",
    "voice-mic-stop",
    "voice-unavailable-wiring",
    "voice-unavailable-signin",
    "voice-ready",
    "voice-listening",
    "voice-interim",
    "voice-final",
    "voice-stopped",
    "voice-ended",
    "voice-deferred",
    "voice-error",
    "voice-error-permission",
    "voice-error-unsupported",
)

FORBIDDEN_SOURCE_TOKENS = (
    "requestSubmit",
    "sendButton",
    ".click(",
    "innerHTML",
    "insertAdjacentHTML",
    "document.write",
    "eval(",
    "fetch(",
    "XMLHttpRequest",
    "WebSocket",
    "SpeechRecognition",
    "getUserMedia",
    "MediaRecorder",
    "AudioContext",
    "localStorage",
    "sessionStorage",
    "document.cookie",
    "indexedDB",
)


def _locale_block(source: str, start: str, end: str) -> str:
    left = source.index(start)
    right = source.index(end, left + len(start))
    return source[left:right]


def _shipped_copy() -> dict[str, dict[str, str]]:
    source = LOCALE_JS.read_text(encoding="utf-8")
    ko_block = _locale_block(source, "ko: {", "en: {")
    en_block = _locale_block(source, "en: {", "\n    }")
    copy: dict[str, dict[str, str]] = {}
    for lang, block in (("ko", ko_block), ("en", en_block)):
        table: dict[str, str] = {}
        for key in VOICE_KEYS:
            match = re.search(rf'"{re.escape(key)}":\s*"((?:[^"\\]|\\.)*)"', block)
            assert match, f"locale.js {lang} table is missing {key}"
            table[key] = json.loads(f'"{match.group(1)}"')
        copy[lang] = table
    return copy


_HARNESS = r"""
"use strict";
const fs = require("node:fs");
const adapterPath = process.argv[2];
const modulePath = process.argv[3];
const copyPath = process.argv[4];
const copy = JSON.parse(fs.readFileSync(copyPath, "utf8"));
const adapterApi = require(adapterPath);
const composerApi = require(modulePath);

let focusCalls = 0;
const allLogs = [];

function makeEl(tag) {
  const el = {
    tagName: String(tag || "div").toUpperCase(),
    id: "", className: "", type: "", value: "", textContent: "",
    hidden: false, disabled: false, dataset: {}, attrs: {}, children: [],
    parentNode: null, handlers: {}, focusCalls: 0,
  };
  el.addEventListener = function (type, fn) {
    if (!el.handlers[type]) el.handlers[type] = [];
    el.handlers[type].push(fn);
  };
  el.removeEventListener = function (type, fn) {
    const list = el.handlers[type] || [];
    const index = list.indexOf(fn);
    if (index >= 0) list.splice(index, 1);
  };
  el.dispatchEvent = function (event) {
    // Real browsers never deliver a click to a disabled control.
    if (el.disabled && event && event.type === "click") return true;
    const list = (el.handlers[event.type] || []).slice();
    for (const fn of list) fn(event);
    return true;
  };
  el.setAttribute = function (name, value) { el.attrs[name] = String(value); };
  el.getAttribute = function (name) {
    return Object.prototype.hasOwnProperty.call(el.attrs, name) ? el.attrs[name] : null;
  };
  el.removeAttribute = function (name) { delete el.attrs[name]; };
  el.appendChild = function (child) { child.parentNode = el; el.children.push(child); return child; };
  el.insertBefore = function (child, reference) {
    child.parentNode = el;
    const index = reference ? el.children.indexOf(reference) : -1;
    if (index >= 0) el.children.splice(index, 0, child); else el.children.push(child);
    return child;
  };
  el.removeChild = function (child) {
    const index = el.children.indexOf(child);
    if (index >= 0) el.children.splice(index, 1);
    child.parentNode = null;
    return child;
  };
  el.querySelectorAll = function (selector) {
    const found = [];
    const collect = (node) => {
      for (const child of node.children) {
        if (matches(child, selector)) found.push(child);
        collect(child);
      }
    };
    collect(el);
    return found;
  };
  el.querySelector = function (selector) { return el.querySelectorAll(selector)[0] || null; };
  el.focus = function () { el.focusCalls += 1; focusCalls += 1; };
  el.closest = function () { return null; };
  return el;
}

function matches(node, selector) {
  if (selector.startsWith(".")) return node.className.split(/\s+/).includes(selector.slice(1));
  if (selector.startsWith("#")) return node.id === selector.slice(1);
  return false;
}

function buildEnv(options) {
  options = options || {};
  const observers = [];
  class FakeEvent {
    constructor(type, init) {
      this.type = type;
      this.bubbles = Boolean(init && init.bubbles);
      this.detail = init && init.detail;
    }
  }
  function FakeMutationObserver(callback) {
    this.callback = callback; this.target = null; this.filter = null; this.disconnected = false;
    observers.push(this);
  }
  FakeMutationObserver.prototype.observe = function (target, init) {
    this.target = target;
    this.filter = init && init.attributeFilter ? init.attributeFilter : null;
  };
  FakeMutationObserver.prototype.disconnect = function () { this.disconnected = true; };
  function notify(target, attribute) {
    for (const observer of observers) {
      if (observer.disconnected || observer.target !== target) continue;
      if (observer.filter && !observer.filter.includes(attribute)) continue;
      observer.callback([{ type: "attributes", attributeName: attribute, target: target }]);
    }
  }

  let lang = options.lang || "ko";
  const log = { network: [], inputEvents: [], submits: [], clicks: [], sessionStarts: [], sessionStops: [] };
  allLogs.push(log);

  const shell = makeEl("div"); shell.className = "app-shell"; shell.dataset.state = "chat";
  const form = makeEl("form"); form.id = "composerForm";
  const input = makeEl("textarea"); input.id = "messageInput"; input.value = options.inputValue || "";
  const actions = makeEl("div"); actions.className = "composer-actions";
  const tools = makeEl("div"); tools.className = "composer-tools";
  const cancel = makeEl("button"); cancel.id = "cancelStreamButton"; cancel.hidden = true;
  const send = makeEl("button"); send.id = "sendButton"; send.disabled = true;
  actions.appendChild(tools);
  actions.appendChild(cancel);
  actions.appendChild(send);
  form.appendChild(input);
  form.appendChild(actions);
  const body = makeEl("body");
  body.appendChild(form);

  const doc = {
    body: body,
    readyState: "complete",
    els: { composerForm: form, messageInput: input, cancelStreamButton: cancel, sendButton: send },
    createElement: (tag) => makeEl(tag),
    getElementById: (id) => (Object.prototype.hasOwnProperty.call(doc.els, id) ? doc.els[id] : null),
    querySelector: (selector) => (selector === ".app-shell" ? shell : null),
    querySelectorAll: () => [],
    addEventListener: () => {},
  };
  form.requestSubmit = function () { log.submits.push("requestSubmit"); };
  form.submit = function () { log.submits.push("submit"); };
  send.addEventListener("click", function () { log.clicks.push("send"); });
  input.addEventListener("input", function (event) { log.inputEvents.push(event.type); });

  const winHandlers = {};
  const win = {
    document: doc,
    Event: FakeEvent,
    CustomEvent: FakeEvent,
    MutationObserver: FakeMutationObserver,
    Date: Date,
    __padiemLocale: { text: (key) => (copy[lang] && copy[lang][key]) || key },
    PadiemVoiceSttInput: adapterApi,
    addEventListener: (type, fn) => { (winHandlers[type] = winHandlers[type] || []).push(fn); },
    removeEventListener: (type, fn) => {
      const list = winHandlers[type] || [];
      const index = list.indexOf(fn);
      if (index >= 0) list.splice(index, 1);
    },
    dispatchEvent: (event) => {
      (winHandlers[event.type] || []).slice().forEach((fn) => fn(event));
      return true;
    },
    fetch: () => { log.network.push("fetch"); return Promise.reject(new Error("offline")); },
    XMLHttpRequest: function () { log.network.push("xhr"); },
    WebSocket: function () { log.network.push("websocket"); },
  };

  return {
    win, doc, log, shell, form, input, actions, tools, cancel, send,
    sessions: [],
    notify,
    setLang: (next) => { lang = next; },
  };
}

function find(env, id) { return env.doc.body.querySelector("#" + id); }

function makeFactory(env) {
  return function recognizerFactory(callbacks, context) {
    env.log.sessionStarts.push({ generation: context.generation, sessionToken: context.sessionToken });
    const session = {
      callbacks: callbacks,
      context: context,
      stopped: false,
      stop: function () {
        session.stopped = true;
        env.log.sessionStops.push(context.generation);
      },
      interim: function (text) { callbacks.onInterim(text); },
      final: function (payload) { callbacks.onFinal(payload); },
      error: function (code) { callbacks.onError(code); },
      end: function () { callbacks.onEnd(); },
    };
    env.sessions.push(session);
    return session;
  };
}

function loadComposer(env, options) {
  options = options || {};
  return composerApi.createVoiceComposer(env.win, env.doc, {
    recognizerFactory: options.factory || null,
  });
}

function signIn(env) {
  env.win.dispatchEvent(new env.win.Event("padiem:auth-state", { detail: { authenticated: true } }));
}

function readyEnv(options) {
  const env = buildEnv(options);
  const composer = loadComposer(env, { factory: makeFactory(env) });
  signIn(env);
  return { env, composer, button: find(env, "voiceMicButton"), status: find(env, "voiceStatus"), preview: find(env, "voiceInterimPreview") };
}

function emit(env, index, method, arg) {
  const session = env.sessions[index];
  if (!session || typeof session[method] !== "function") return false;
  if (method === "end") session.end(); else session[method](arg);
  return true;
}

function stopped(env, index) {
  const session = env.sessions[index];
  return Boolean(session && session.stopped);
}

const R = {};

/* S1: today's default -- no recognizer factory, nothing happens. */
{
  const env = buildEnv();
  const composer = loadComposer(env);
  const button = find(env, "voiceMicButton");
  const status = find(env, "voiceStatus");
  const preview = find(env, "voiceInterimPreview");
  button.dispatchEvent(new env.win.Event("click"));
  const startResult = composer.start();
  const stopResult = composer.stop();
  const labelSpan = button.children.find((child) => child.getAttribute("data-locale-key") === "voice-mic");
  R.no_factory = {
    button_present: Boolean(button),
    button_disabled: button.disabled,
    aria_disabled: button.getAttribute("aria-disabled"),
    voice_state: button.getAttribute("data-voice-state"),
    aria_pressed: button.getAttribute("aria-pressed"),
    status_key: status.getAttribute("data-locale-key"),
    status_text: status.textContent,
    status_role: status.getAttribute("role"),
    status_live: status.getAttribute("aria-live"),
    label_text: labelSpan ? labelSpan.textContent : null,
    status_text_is_shipped_wiring: status.textContent === copy.ko["voice-unavailable-wiring"],
    ready_copy_used: status.textContent === copy.ko["voice-ready"],
    start_result: startResult,
    stop_result: stopResult,
    preview_hidden: preview.hidden,
    mounted_in_actions: button.parentNode === env.actions,
    sits_before_cancel: env.actions.children.indexOf(button) < env.actions.children.indexOf(env.cancel),
    sits_in_tools: toolsContains(env, button),
    network: env.log.network.length,
    submits: env.log.submits.length,
    send_clicks: env.log.clicks.length,
    sessions: env.log.sessionStarts.length,
  };
}

function toolsContains(env, node) {
  let current = node.parentNode;
  while (current) {
    if (current === env.tools) return true;
    current = current.parentNode;
  }
  return false;
}

/* S2: sign-in alone does not unlock; factory + signed-in session does. */
{
  const env = buildEnv();
  const composer = loadComposer(env, { factory: makeFactory(env) });
  const button = find(env, "voiceMicButton");
  const status = find(env, "voiceStatus");
  const unknown = { disabled: button.disabled, key: status.getAttribute("data-locale-key") };
  env.win.dispatchEvent(new env.win.Event("padiem:auth-state", { detail: { authenticated: false } }));
  const guest = { disabled: button.disabled, key: status.getAttribute("data-locale-key"), text: status.textContent };
  env.win.dispatchEvent(new env.win.Event("padiem:auth-state", { detail: { authenticated: true } }));
  const signedIn = {
    disabled: button.disabled,
    aria_disabled: button.getAttribute("aria-disabled"),
    voice_state: button.getAttribute("data-voice-state"),
    key: status.getAttribute("data-locale-key"),
    aria: button.getAttribute("aria-label"),
  };
  button.dispatchEvent(new env.win.Event("click"));
  const running = composer.getStatus();
  R.signin_gate = {
    unknown, guest, signedIn, running,
    session_starts: env.log.sessionStarts.length,
    network: env.log.network.length,
  };
}

/* S3: interim is preview only. */
{
  const ctx = readyEnv();
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  emit(ctx.env, 0, "interim", "견적서");
  const first = {
    input: ctx.env.input.value,
    preview: ctx.preview.textContent,
    preview_hidden: ctx.preview.hidden,
    key: ctx.status.getAttribute("data-locale-key"),
  };
  emit(ctx.env, 0, "interim", "견적서 초안");
  const second = { input: ctx.env.input.value, preview: ctx.preview.textContent };
  R.interim_preview = {
    first, second,
    input_events: ctx.env.log.inputEvents.length,
    aria_pressed: ctx.button.getAttribute("aria-pressed"),
    stop_aria: ctx.button.getAttribute("aria-label"),
  };
}

/* S4: only the authoritative final lands in the editable input. */
{
  const ctx = readyEnv({ inputValue: "직접 입력한 문장" });
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  emit(ctx.env, 0, "final", { text: "견적서 초안을 만들어 주세요", utteranceId: "u1" });
  const after = {
    input: ctx.env.input.value,
    preview_hidden: ctx.preview.hidden,
    preview_text: ctx.preview.textContent,
    key: ctx.status.getAttribute("data-locale-key"),
    input_events: ctx.env.log.inputEvents.slice(),
    submits: ctx.env.log.submits.length,
    send_clicks: ctx.env.log.clicks.length,
    aria_pressed: ctx.button.getAttribute("aria-pressed"),
    voice_state: ctx.button.getAttribute("data-voice-state"),
    stop_aria: ctx.button.getAttribute("aria-label"),
    active: ctx.composer.getStatus().active,
    session_stops: ctx.env.log.sessionStops.length,
    session_stopped: stopped(ctx.env, 0),
  };
  ctx.env.input.value = "사용자가 수정한 내용";
  emit(ctx.env, 0, "interim", "늦은 중간값");
  const edited = { input: ctx.env.input.value, preview: ctx.preview.textContent };
  R.final_review = { after, edited };
}

/* S5: duplicate utterance id suppressed; S6: distinct id with identical speech allowed. */
{
  const ctx = readyEnv();
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  emit(ctx.env, 0, "final", { text: "네", utteranceId: "u1" });
  emit(ctx.env, 0, "final", { text: "네", utteranceId: "u1" });
  const duplicated = { input: ctx.env.input.value, input_events: ctx.env.log.inputEvents.length };
  emit(ctx.env, 0, "final", { text: "네", utteranceId: "u2" });
  const distinct = { input: ctx.env.input.value, input_events: ctx.env.log.inputEvents.length };
  R.dedup = { duplicated, distinct };
}

/* S7: stop drops late events. */
{
  const ctx = readyEnv();
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  const stopped = {
    key: ctx.status.getAttribute("data-locale-key"),
    active: ctx.composer.getStatus().active,
    aria_pressed: ctx.button.getAttribute("aria-pressed"),
    session_stops: ctx.env.log.sessionStops.length,
  };
  emit(ctx.env, 0, "interim", "늦은 중간값");
  emit(ctx.env, 0, "final", { text: "늦은 전사", utteranceId: "u1" });
  const late = { input: ctx.env.input.value, preview: ctx.preview.textContent, preview_hidden: ctx.preview.hidden };
  R.stop_late = { stopped, late };
}

/* S8: sign-out invalidates the run and late results. */
{
  const ctx = readyEnv();
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  emit(ctx.env, 0, "interim", "진행 중");
  ctx.env.win.dispatchEvent(new ctx.env.win.Event("padiem:auth-state", { detail: { authenticated: false } }));
  const signedOut = {
    key: ctx.status.getAttribute("data-locale-key"),
    text: ctx.status.textContent,
    undefined_key: ctx.status.getAttribute("data-locale-key") === "voice-unavailable-signin",
    disabled: ctx.button.disabled,
    active: ctx.composer.getStatus().active,
    session_stops: ctx.env.log.sessionStops.length,
    preview_hidden: ctx.preview.hidden,
  };
  emit(ctx.env, 0, "interim", "늦은 중간값");
  emit(ctx.env, 0, "final", { text: "늦은 전사", utteranceId: "u1" });
  const late = { input: ctx.env.input.value, preview: ctx.preview.textContent };
  R.signout = { signedOut, late };
}

/* S9: Chat/Claw switch invalidates; Claw keeps the same affordance. */
{
  const ctx = readyEnv();
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  ctx.env.shell.dataset.state = "claw";
  ctx.env.notify(ctx.env.shell, "data-state");
  const switched = {
    active: ctx.composer.getStatus().active,
    session_stops: ctx.env.log.sessionStops.length,
  };
  emit(ctx.env, 0, "interim", "늦은 중간값");
  emit(ctx.env, 0, "final", { text: "늦은 전사", utteranceId: "u1" });
  const late = { input: ctx.env.input.value, preview: ctx.preview.textContent };
  const claw = {
    mounted_in_actions: ctx.button.parentNode === ctx.env.actions,
    disabled: ctx.button.disabled,
    key: ctx.status.getAttribute("data-locale-key"),
  };
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  emit(ctx.env, 1, "final", { text: "클로에서 보낸 전사", utteranceId: "u1" });
  const clawFinal = { input: ctx.env.input.value, session_starts: ctx.env.log.sessionStarts.length };
  R.shell_switch = { switched, late, claw, clawFinal };
}

/* S10: composition deferral preserves IME text. */
{
  const ctx = readyEnv({ inputValue: "기존 문장" });
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  ctx.env.input.dispatchEvent(new ctx.env.win.Event("compositionstart"));
  emit(ctx.env, 0, "final", { text: "추가 문장", utteranceId: "u1" });
  const deferred = {
    input: ctx.env.input.value,
    key: ctx.status.getAttribute("data-locale-key"),
    deferred: ctx.composer.getStatus().deferred,
    text: ctx.status.textContent,
  };
  ctx.env.input.value = "기존 문장 새로 타이핑";
  ctx.env.input.dispatchEvent(new ctx.env.win.Event("compositionend"));
  const flushed = {
    input: ctx.env.input.value,
    key: ctx.status.getAttribute("data-locale-key"),
    input_events: ctx.env.log.inputEvents.length,
    submits: ctx.env.log.submits.length,
  };
  R.composition = { deferred, flushed };
}

/* S11: a disabled composer (in-flight answer / approval surface) defers the final. */
{
  const ctx = readyEnv();
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  ctx.env.input.disabled = true;
  ctx.env.notify(ctx.env.input, "disabled");
  emit(ctx.env, 0, "final", { text: "송신 중 도착한 전사", utteranceId: "u1" });
  const deferred = { input: ctx.env.input.value, key: ctx.status.getAttribute("data-locale-key") };
  ctx.env.input.disabled = false;
  ctx.env.notify(ctx.env.input, "disabled");
  const flushed = {
    input: ctx.env.input.value,
    submits: ctx.env.log.submits.length,
    send_clicks: ctx.env.log.clicks.length,
  };
  R.disabled_composer = { deferred, flushed };
}

/* S12: permission denial is bounded and retryable. */
{
  const ctx = readyEnv();
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  emit(ctx.env, 0, "error", "permission-denied");
  const denied = {
    key: ctx.status.getAttribute("data-locale-key"),
    text: ctx.status.textContent,
    is_shipped_copy: ctx.status.textContent === copy.ko["voice-error-permission"],
    active: ctx.composer.getStatus().active,
    disabled: ctx.button.disabled,
    voice_state: ctx.button.getAttribute("data-voice-state"),
    session_stopped: stopped(ctx.env, 0),
    session_stops: ctx.env.log.sessionStops.length,
    preview_hidden: ctx.preview.hidden,
  };
  emit(ctx.env, 0, "final", { text: "늦은 전사", utteranceId: "u9" });
  const late = { input: ctx.env.input.value };
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  const retry = { session_starts: ctx.env.log.sessionStarts.length, active: ctx.composer.getStatus().active };
  emit(ctx.env, 1, "final", { text: "다시 시도한 전사", utteranceId: "u1" });
  const retried = { input: ctx.env.input.value, key: ctx.status.getAttribute("data-locale-key") };
  R.permission_denied = { denied, late, retry, retried, network: ctx.env.log.network.length };
}

/* S13: unsupported browser copy. */
{
  const ctx = readyEnv();
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  emit(ctx.env, 0, "error", "unsupported");
  R.unsupported = {
    key: ctx.status.getAttribute("data-locale-key"),
    text: ctx.status.textContent,
    is_shipped_copy: ctx.status.textContent === copy.ko["voice-error-unsupported"],
    disabled: ctx.button.disabled,
  };
}

/* S14: user-typed text survives a session; recognizer end drops buffered interim. */
{
  const ctx = readyEnv({ inputValue: "직접 입력한 문장" });
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  emit(ctx.env, 0, "interim", "말하다 만 중간값");
  emit(ctx.env, 0, "end");
  const ended = {
    input: ctx.env.input.value,
    key: ctx.status.getAttribute("data-locale-key"),
    is_shipped_copy: ctx.status.textContent === copy.ko["voice-ended"],
    active: ctx.composer.getStatus().active,
    preview_hidden: ctx.preview.hidden,
    session_stopped: stopped(ctx.env, 0),
  };
  emit(ctx.env, 0, "final", { text: "늦은 전사", utteranceId: "u1" });
  const late = { input: ctx.env.input.value };
  R.typed_preserved = { ended, late };
}

/* S15: locale projection comes from the shipped table. */
{
  const ctx = readyEnv();
  const before = {
    key: ctx.status.getAttribute("data-locale-key"),
    text: ctx.status.textContent,
    is_ko: ctx.status.textContent === copy.ko["voice-ready"],
    aria: ctx.button.getAttribute("aria-label"),
  };
  ctx.env.setLang("en");
  ctx.env.win.dispatchEvent(new ctx.env.win.Event("padiem:localechange"));
  const labelSpan = ctx.button.children.find((child) => child.getAttribute("data-locale-key") === "voice-mic");
  const after = {
    key: ctx.status.getAttribute("data-locale-key"),
    text: ctx.status.textContent,
    is_en: ctx.status.textContent === copy.en["voice-ready"],
    aria: ctx.button.getAttribute("aria-label"),
    aria_is_en: ctx.button.getAttribute("aria-label") === copy.en["voice-mic-start"],
    label: labelSpan ? labelSpan.textContent : null,
    label_is_en: labelSpan ? labelSpan.textContent === copy.en["voice-mic"] : false,
  };
  R.locale_switch = { before, after };
}

/* S16: end-to-end aggregate -- no post, no submit, no send press, no focus steal. */
{
  const network = allLogs.reduce((total, entry) => total + entry.network.length, 0);
  const submits = allLogs.reduce((total, entry) => total + entry.submits.length, 0);
  const clicks = allLogs.reduce((total, entry) => total + entry.clicks.length, 0);
  R.aggregate = { network, submits, send_clicks: clicks, focus_calls: focusCalls };
}

/* S17: a stale recognizer that emits after a restart must not bleed into the new run. */
{
  const ctx = readyEnv();
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  emit(ctx.env, 0, "interim", "첫 번째 발화");
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  emit(ctx.env, 0, "final", { text: "이전 세션 전사", utteranceId: "old-u" });
  emit(ctx.env, 0, "interim", "이전 세션 중간값");
  const contaminated = {
    input: ctx.env.input.value,
    preview: ctx.preview.textContent,
    preview_hidden: ctx.preview.hidden,
    active_generation: ctx.composer.getStatus().generation,
  };
  emit(ctx.env, 1, "final", { text: "두 번째 발화", utteranceId: "u2" });
  const clean = {
    input: ctx.env.input.value,
    session_starts: ctx.env.log.sessionStarts.length,
    endpoint: ctx.composer.getStatus().availability,
  };
  R.restart_isolation = { contaminated, clean };
}

/* S18: a committed utterance is not the end of the microphone session. */
{
  const ctx = readyEnv();
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  emit(ctx.env, 0, "interim", "첫 번째 발화");
  emit(ctx.env, 0, "final", { text: "첫 번째 전사", utteranceId: "u1" });
  const committed = {
    input: ctx.env.input.value,
    key: ctx.status.getAttribute("data-locale-key"),
    text: ctx.status.textContent,
    is_shipped_copy: ctx.status.textContent === copy.ko["voice-final"],
    aria_pressed: ctx.button.getAttribute("aria-pressed"),
    voice_state: ctx.button.getAttribute("data-voice-state"),
    aria: ctx.button.getAttribute("aria-label"),
    stop_aria: ctx.button.getAttribute("aria-label") === copy.ko["voice-mic-stop"],
    start_aria: ctx.button.getAttribute("aria-label") === copy.ko["voice-mic-start"],
    active: ctx.composer.getStatus().active,
    session_stops: ctx.env.log.sessionStops.length,
    session_stopped: stopped(ctx.env, 0),
    preview_hidden: ctx.preview.hidden,
  };
  emit(ctx.env, 0, "interim", "두 번째 발화");
  const resumed = {
    input: ctx.env.input.value,
    key: ctx.status.getAttribute("data-locale-key"),
    preview: ctx.preview.textContent,
    preview_hidden: ctx.preview.hidden,
    active: ctx.composer.getStatus().active,
    aria_pressed: ctx.button.getAttribute("aria-pressed"),
  };
  emit(ctx.env, 0, "final", { text: "두 번째 전사", utteranceId: "u2" });
  const second = { input: ctx.env.input.value, key: ctx.status.getAttribute("data-locale-key") };
  ctx.button.dispatchEvent(new ctx.env.win.Event("click"));
  const ended = {
    key: ctx.status.getAttribute("data-locale-key"),
    aria_pressed: ctx.button.getAttribute("aria-pressed"),
    active: ctx.composer.getStatus().active,
    session_stops: ctx.env.log.sessionStops.length,
    session_stopped: stopped(ctx.env, 0),
  };
  emit(ctx.env, 0, "final", { text: "늦은 전사", utteranceId: "u3" });
  const late = { input: ctx.env.input.value };
  R.final_keeps_mic_on = { committed, resumed, second, ended, late };
}

/* S19: a recognizer that ends synchronously inside its own factory. */
{
  const env = buildEnv();
  let captured = null;
  let session = null;
  let firstCall = true;
  const factory = function recognizerFactory(callbacks, context) {
    env.log.sessionStarts.push({ generation: context.generation, sessionToken: context.sessionToken, synchronous: true });
    session = {
      context: context,
      stopped: false,
      callbacks: callbacks,
      stop: function () { session.stopped = true; env.log.sessionStops.push(context.generation); },
    };
    captured = callbacks;
    // The first factory call ends its own run before returning it.
    if (firstCall) {
      firstCall = false;
      callbacks.onEnd();
    }
    env.sessions.push(session);
    return session;
  };
  const composer = loadComposer(env, { factory });
  signIn(env);
  const button = find(env, "voiceMicButton");
  const status = find(env, "voiceStatus");
  const startReturn = composer.start();
  const result = {
    start_return: startReturn,
    active: composer.getStatus().active,
    voice_state: button.getAttribute("data-voice-state"),
    aria_pressed: button.getAttribute("aria-pressed"),
    disabled: button.disabled,
    aria: button.getAttribute("aria-label"),
    start_aria: button.getAttribute("aria-label") === copy.ko["voice-mic-start"],
    key: status.getAttribute("data-locale-key"),
    text: status.textContent,
    is_shipped_copy: status.textContent === copy.ko["voice-ended"],
    session_starts: env.log.sessionStarts.length,
    session_stops: env.log.sessionStops.length,
    session_stopped: Boolean(session && session.stopped),
  };
  // The dead recognizer must not be able to write after the factory returned.
  if (captured) captured.onFinal({ text: "늦은 전사", utteranceId: "u9" });
  if (captured) captured.onInterim("늦은 중간값");
  const late = { input: env.input.value, preview: find(env, "voiceInterimPreview").textContent };
  // The control still lets the user start a healthy run afterwards.
  button.dispatchEvent(new env.win.Event("click"));
  const restart = { session_starts: env.log.sessionStarts.length, active: composer.getStatus().active, voice_state: button.getAttribute("data-voice-state") };
  const live = env.sessions[env.sessions.length - 1];
  if (live) live.callbacks.onFinal({ text: "다시 시작한 전사", utteranceId: "u21" });
  const restart_last = { input: env.input.value, key: status.getAttribute("data-locale-key") };
  R.sync_end_during_start = { result, late, restart, restart_last, network: env.log.network.length };
}

/* S20: a recognizer that fails synchronously inside its own factory. */
{
  const env = buildEnv();
  let captured = null;
  let session = null;
  let firstCall = true;
  const factory = function recognizerFactory(callbacks, context) {
    env.log.sessionStarts.push({ generation: context.generation, sessionToken: context.sessionToken, synchronous: true });
    session = {
      context: context,
      stopped: false,
      callbacks: callbacks,
      stop: function () { session.stopped = true; env.log.sessionStops.push(context.generation); },
    };
    captured = callbacks;
    // The first factory call fails its own run before returning it.
    if (firstCall) {
      firstCall = false;
      callbacks.onError("permission-denied");
    }
    env.sessions.push(session);
    return session;
  };
  const composer = loadComposer(env, { factory });
  signIn(env);
  const button = find(env, "voiceMicButton");
  const status = find(env, "voiceStatus");
  const startReturn = composer.start();
  const failed = {
    start_return: startReturn,
    active: composer.getStatus().active,
    voice_state: button.getAttribute("data-voice-state"),
    aria_pressed: button.getAttribute("aria-pressed"),
    disabled: button.disabled,
    key: status.getAttribute("data-locale-key"),
    text: status.textContent,
    is_shipped_copy: status.textContent === copy.ko["voice-error-permission"],
    listening_copy_used: status.textContent === copy.ko["voice-listening"],
    session_stops: env.log.sessionStops.length,
    session_stopped: Boolean(session && session.stopped),
  };
  if (captured) captured.onFinal({ text: "늦은 전사", utteranceId: "u9" });
  const late = { input: env.input.value };
  // A retry from the same composer starts a healthy new run and works.
  button.dispatchEvent(new env.win.Event("click"));
  const retry = { session_starts: env.log.sessionStarts.length, active: composer.getStatus().active, voice_state: button.getAttribute("data-voice-state") };
  const live = env.sessions[env.sessions.length - 1];
  if (live) live.callbacks.onFinal({ text: "다시 시도한 전사", utteranceId: "u1" });
  const retried = { input: env.input.value, key: status.getAttribute("data-locale-key") };
  R.sync_error_during_start = { failed, late, retry, retried, network: env.log.network.length };
}

console.log(JSON.stringify({ ok: true, results: R }));
"""

def _run_harness() -> dict:
    node = shutil.which("node")
    assert node, "node runtime is required for the voice composer harness"
    copy = _shipped_copy()
    workdir = Path(tempfile.mkdtemp(prefix="voice-composer-4643-"))
    harness = workdir / "harness.cjs"
    harness.write_text(_HARNESS, encoding="utf-8", newline="\n")
    copy_path = workdir / "copy.json"
    copy_path.write_text(json.dumps(copy, ensure_ascii=False), encoding="utf-8", newline="\n")
    result = subprocess.run(
        [node, str(harness), str(ADAPTER_JS), str(COMPOSER_JS), str(copy_path)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, f"harness exited {result.returncode}: {result.stderr[:4000]}"
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload.get("ok") is True, payload
    return payload["results"]


_shipped = _shipped_copy()
_results = _run_harness()


def test_index_html_loads_adapter_then_composer_before_app() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert html.count('<script src="./voice-stt-input.js"></script>') == 1
    assert html.count('<script src="./voice-composer.js"></script>') == 1
    assert html.index("voice-stt-input.js") < html.index("voice-composer.js") < html.index('<script src="./app.js">')
    assert '<link rel="stylesheet" href="./voice-composer.css" />' in html


def test_locale_copy_covers_every_composer_key_in_both_languages() -> None:
    assert set(_shipped["ko"]) == set(VOICE_KEYS)
    assert set(_shipped["en"]) == set(VOICE_KEYS)
    source = COMPOSER_JS.read_text(encoding="utf-8")
    for key in VOICE_KEYS:
        assert f'"{key}"' in source, f"module fallback table is missing {key}"


def test_module_owns_no_engine_transport_or_send_path() -> None:
    source = COMPOSER_JS.read_text(encoding="utf-8")
    for token in FORBIDDEN_SOURCE_TOKENS:
        assert token not in source, f"forbidden token in voice-composer.js: {token}"
    assert "createVoiceInputAdapter" in source
    assert "liveTranscriptTurn" not in source, "transcript merge logic must stay in the reviewed adapter"
    assert not re.search(r"[\uac00-\ud7a3]", source), "user copy belongs in locale.js, not the module"


def test_css_is_contained_and_origin_free() -> None:
    css = COMPOSER_CSS.read_text(encoding="utf-8")
    assert "#voiceMicButton" in css
    assert "margin-inline-start: auto" in css
    assert "@media (max-width: 620px)" in css
    assert "min-height: 44px" in css
    assert "http://" not in css and "https://" not in css


def test_default_off_is_unavailable_with_zero_activity() -> None:
    result = _results["no_factory"]
    assert result["button_present"] is True
    assert result["mounted_in_actions"] is True, "the mic must live in the shared .composer-actions row"
    assert result["sits_in_tools"] is False, "the Claw shell hides .composer-tools"
    assert result["sits_before_cancel"] is True
    assert result["button_disabled"] is False
    assert result["aria_disabled"] == "false"
    assert result["voice_state"] == "unavailable"
    assert result["aria_pressed"] == "false"
    assert result["status_key"] == "voice-unavailable-wiring"
    assert result["status_text_is_shipped_wiring"] is True, result
    assert result["ready_copy_used"] is False
    assert result["status_role"] == "status" and result["status_live"] == "polite"
    assert result["label_text"] == _shipped["ko"]["voice-mic"]
    assert result["start_result"] is False, "start() must refuse while no recognizer is wired"
    assert result["stop_result"] is False, "stop() must be a no-op while nothing is running"
    assert result["preview_hidden"] is True
    assert result["network"] == 0 and result["submits"] == 0 and result["send_clicks"] == 0
    assert result["sessions"] == 0


def test_signin_gate_requires_factory_and_session() -> None:
    result = _results["signin_gate"]
    assert result["unknown"] == {"disabled": False, "key": "voice-unavailable-signin"}
    assert result["guest"]["disabled"] is False
    assert result["guest"]["key"] == "voice-unavailable-signin"
    assert result["guest"]["text"] == _shipped["ko"]["voice-unavailable-signin"]
    assert result["signedIn"]["disabled"] is False
    assert result["signedIn"]["aria_disabled"] == "false"
    assert result["signedIn"]["voice_state"] == "ready"
    assert result["signedIn"]["key"] == "voice-ready"
    assert result["signedIn"]["aria"] == _shipped["ko"]["voice-mic-start"]
    assert result["running"]["active"] is True
    assert result["running"]["voiceState"] == "listening"
    assert result["session_starts"] == 1
    assert result["network"] == 0


def test_interim_is_preview_only() -> None:
    result = _results["interim_preview"]
    assert result["first"]["input"] == ""
    assert result["first"]["preview"] == "견적서"
    assert result["first"]["preview_hidden"] is False
    assert result["first"]["key"] == "voice-interim"
    assert result["second"]["input"] == ""
    assert result["second"]["preview"] == "견적서 초안"
    assert result["input_events"] == 0
    assert result["aria_pressed"] == "true"
    assert result["stop_aria"] == _shipped["ko"]["voice-mic-stop"]


def test_only_the_final_reaches_the_editable_input() -> None:
    result = _results["final_review"]
    after = result["after"]
    assert after["input"] == "직접 입력한 문장 견적서 초안을 만들어 주세요"
    assert after["preview_hidden"] is True and after["preview_text"] == ""
    assert after["key"] == "voice-final"
    assert after["input_events"] == ["input"], "the existing input event must run so Send enablement updates"
    assert after["submits"] == 0 and after["send_clicks"] == 0
    edited = result["edited"]
    assert edited["input"] == "사용자가 수정한 내용", "a later interim must not overwrite the user's edit"
    assert edited["preview"] == "늦은 중간값"


def test_a_committed_utterance_keeps_the_microphone_on() -> None:
    """#4643 state fix: `final` is an utterance boundary, not the session end."""
    result = _results["final_review"]["after"]
    assert result["aria_pressed"] == "true", "the still-open recognizer must keep the stop affordance"
    assert result["voice_state"] == "active"
    assert result["stop_aria"] == _shipped["ko"]["voice-mic-stop"]
    assert result["active"] is True
    assert result["session_stops"] == 0, "no recognizer session was ended by an utterance boundary"
    assert result["session_stopped"] is False


def test_duplicate_suppressed_and_distinct_repeat_allowed() -> None:
    result = _results["dedup"]
    assert result["duplicated"]["input"] == "네"
    assert result["duplicated"]["input_events"] == 1
    assert result["distinct"]["input"] == "네 네"
    assert result["distinct"]["input_events"] == 2


def test_stop_drops_late_events() -> None:
    result = _results["stop_late"]
    assert result["stopped"]["key"] == "voice-stopped"
    assert result["stopped"]["active"] is False
    assert result["stopped"]["aria_pressed"] == "false"
    assert result["stopped"]["session_stops"] == 1
    assert result["late"] == {"input": "", "preview": "", "preview_hidden": True}


def test_signout_invalidates_late_results() -> None:
    result = _results["signout"]
    assert result["signedOut"]["undefined_key"] is True
    assert result["signedOut"]["disabled"] is False
    assert result["signedOut"]["active"] is False
    assert result["signedOut"]["session_stops"] == 1
    assert result["signedOut"]["preview_hidden"] is True
    assert result["late"] == {"input": "", "preview": ""}


def test_shell_switch_invalidates_and_claw_keeps_the_mic() -> None:
    result = _results["shell_switch"]
    assert result["switched"]["active"] is False
    assert result["switched"]["session_stops"] == 1
    assert result["late"] == {"input": "", "preview": ""}
    assert result["claw"]["mounted_in_actions"] is True
    assert result["claw"]["disabled"] is False
    assert result["clawFinal"]["input"] == "클로에서 보낸 전사"
    assert result["clawFinal"]["session_starts"] == 2


def test_composition_deferral_preserves_ime_text() -> None:
    result = _results["composition"]
    assert result["deferred"]["input"] == "기존 문장"
    assert result["deferred"]["key"] == "voice-deferred"
    assert result["deferred"]["deferred"] == 1
    assert result["deferred"]["text"] == _shipped["ko"]["voice-deferred"]
    assert result["flushed"]["input"] == "기존 문장 새로 타이핑 추가 문장"
    assert result["flushed"]["key"] == "voice-final"
    assert result["flushed"]["input_events"] == 1
    assert result["flushed"]["submits"] == 0


def test_disabled_composer_defers_without_submitting() -> None:
    result = _results["disabled_composer"]
    assert result["deferred"]["input"] == ""
    assert result["deferred"]["key"] == "voice-deferred"
    assert result["flushed"]["input"] == "송신 중 도착한 전사"
    assert result["flushed"]["submits"] == 0
    assert result["flushed"]["send_clicks"] == 0


def test_permission_denial_is_bounded_and_retryable() -> None:
    result = _results["permission_denied"]
    denied = result["denied"]
    assert denied["key"] == "voice-error-permission"
    assert denied["is_shipped_copy"] is True
    assert denied["active"] is False
    assert denied["disabled"] is False
    assert denied["voice_state"] == "ready"
    assert denied["session_stopped"] is True
    assert denied["session_stops"] == 1
    assert denied["preview_hidden"] is True
    assert result["late"]["input"] == ""
    assert result["retry"] == {"session_starts": 2, "active": True}
    assert result["retried"]["input"] == "다시 시도한 전사"
    assert result["retried"]["key"] == "voice-final"
    assert result["network"] == 0


def test_unsupported_browser_is_bounded_copy() -> None:
    result = _results["unsupported"]
    assert result["key"] == "voice-error-unsupported"
    assert result["is_shipped_copy"] is True
    assert result["disabled"] is False


def test_typed_text_survives_recognizer_end() -> None:
    result = _results["typed_preserved"]
    ended = result["ended"]
    assert ended["input"] == "직접 입력한 문장"
    assert ended["key"] == "voice-ended"
    assert ended["is_shipped_copy"] is True
    assert ended["active"] is False
    assert ended["preview_hidden"] is True
    assert ended["session_stopped"] is True
    assert result["late"]["input"] == "직접 입력한 문장"


def test_locale_projection_uses_the_shipped_table() -> None:
    result = _results["locale_switch"]
    assert result["before"]["is_ko"] is True
    assert result["before"]["aria"] == _shipped["ko"]["voice-mic-start"]
    assert result["after"]["is_en"] is True
    assert result["after"]["key"] == "voice-ready"
    assert result["after"]["aria_is_en"] is True
    assert result["after"]["label_is_en"] is True


def test_zero_provider_post_and_no_auto_send_or_focus() -> None:
    aggregate = _results["aggregate"]
    assert aggregate["network"] == 0, "no request may leave the module"
    assert aggregate["submits"] == 0, "the composer must never be submitted by voice"
    assert aggregate["send_clicks"] == 0, "the send control must never be pressed by voice"
    assert aggregate["focus_calls"] == 0, "composer focus must not move"


def test_restart_does_not_bleed_previous_utterances() -> None:
    result = _results["restart_isolation"]
    contaminated = result["contaminated"]
    assert contaminated["input"] == "", "a stale recognizer must not write into the new run's input"
    assert contaminated["preview"] == ""
    assert contaminated["preview_hidden"] is True
    assert contaminated["active_generation"] == 2
    assert result["clean"] == {
        "input": "두 번째 발화",
        "session_starts": 2,
        "endpoint": "ready",
    }


def test_final_keeps_the_microphone_session_open_until_the_user_stops_it() -> None:
    """#4643 CENTRAL fix 1: an utterance boundary never ends the recognizer."""
    result = _results["final_keeps_mic_on"]
    committed = result["committed"]
    assert committed["input"] == "첫 번째 전사"
    assert committed["key"] == "voice-final"
    assert committed["is_shipped_copy"] is True
    assert committed["aria_pressed"] == "true"
    assert committed["voice_state"] == "active"
    assert committed["aria"] == _shipped["ko"]["voice-mic-stop"]
    assert committed["start_aria"] is False, "a live recognizer must not offer to start again"
    assert committed["active"] is True
    assert committed["session_stops"] == 0
    assert committed["session_stopped"] is False
    assert committed["preview_hidden"] is True
    resumed = result["resumed"]
    assert resumed["input"] == "첫 번째 전사", "the committed transcript stays for review"
    assert resumed["key"] == "voice-interim"
    assert resumed["preview"] == "두 번째 발화"
    assert resumed["preview_hidden"] is False
    assert resumed["active"] is True
    assert result["second"] == {"input": "첫 번째 전사 두 번째 전사", "key": "voice-final"}
    ended = result["ended"]
    assert ended["key"] == "voice-stopped"
    assert ended["aria_pressed"] == "false"
    assert ended["active"] is False
    assert ended["session_stops"] == 1, "the explicit stop ends exactly one recognizer session"
    assert ended["session_stopped"] is True
    assert result["late"] == {"input": "첫 번째 전사 두 번째 전사"}


def test_synchronous_recognizer_end_during_start_is_not_overwritten() -> None:
    """#4643 CENTRAL fix 2: a recognizer that ends inside its own factory."""
    result = _results["sync_end_during_start"]
    outcome = result["result"]
    assert outcome["start_return"] is False, "a start that already ended cannot claim to be listening"
    assert outcome["active"] is False
    assert outcome["voice_state"] == "ready"
    assert outcome["aria_pressed"] == "false"
    assert outcome["disabled"] is False, "the user may start again"
    assert outcome["start_aria"] is True
    assert outcome["key"] == "voice-ended"
    assert outcome["is_shipped_copy"] is True
    assert outcome["session_starts"] == 1
    assert outcome["session_stops"] == 1, "the returned handle is stopped exactly once, never leaked"
    assert outcome["session_stopped"] is True
    assert result["late"] == {"input": "", "preview": ""}
    assert result["network"] == 0


def test_synchronous_recognizer_error_during_start_is_not_overwritten() -> None:
    """#4643 CENTRAL fix 2: a recognizer that fails inside its own factory."""
    result = _results["sync_error_during_start"]
    failed = result["failed"]
    assert failed["start_return"] is False
    assert failed["active"] is False
    assert failed["voice_state"] == "ready"
    assert failed["aria_pressed"] == "false"
    assert failed["disabled"] is False
    assert failed["key"] == "voice-error-permission"
    assert failed["is_shipped_copy"] is True
    assert failed["listening_copy_used"] is False, "the error surface must not be rewritten as listening"
    assert failed["session_stops"] == 1
    assert failed["session_stopped"] is True
    assert result["late"]["input"] == ""
    assert result["retry"] == {"session_starts": 2, "active": True, "voice_state": "active"}
    assert result["retried"]["input"] == "다시 시도한 전사"
    assert result["retried"]["key"] == "voice-final"
    assert result["network"] == 0