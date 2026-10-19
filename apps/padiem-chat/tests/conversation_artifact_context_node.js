"use strict";
/* #3933: execute the shipped conversation artifact context module with a
 * network-free minimal DOM. It must only resolve the existing owner-scoped
 * GET index route, never read bytes, never grant anything and never guess
 * between same-name completed files. */
const assert = require("node:assert/strict");
const { join } = require("node:path");
const moduleApi = require(join(
  __dirname, "..", "static", "claw-conversation-artifact-context.js"));

const CHAT = "chat_" + "a".repeat(32);
const OTHER_CHAT = "chat_" + "e".repeat(32);
const DOC = "doc_" + "b".repeat(32);
const OTHER_DOC = "doc_" + "d".repeat(32);
const SHA = "c".repeat(64);
const OTHER_SHA = "f".repeat(64);
const NAME = "hark-revised-quote.xlsx";

class FakeNode {
  constructor(tag = "div") {
    this.tag = tag; this.hidden = false; this.disabled = false; this.open = false;
    this.textContent = ""; this.className = ""; this.type = "";
    this.children = []; this.handlers = {};
  }
  addEventListener(name, callback) { this.handlers[name] = callback; }
  append(...elements) { this.children.push(...elements); }
  appendChild(node) { this.children.push(node); }
  replaceChildren(...nodes) { this.children = nodes; }
  setAttribute(name, value) { this[name] = value; }
  querySelector() { return null; }
  scrollIntoView() { this.scrolled = true; }
  async click() { return this.handlers.click?.(); }
}

function fakeDocument({ panel = null } = {}) {
  return {
    panel,
    createElement(tag) { return new FakeNode(tag); },
    getElementById(id) { return id === "clawWebOfficeDetails" ? panel : null; },
  };
}

function fakeHost(doc) {
  return {
    hidden: true, children: [], ownerDocument: doc, attributes: {},
    append(...elements) { this.children.push(...elements); },
    replaceChildren(...nodes) { this.children = nodes; },
    setAttribute(name, value) { this.attributes[name] = value; },
  };
}

function textOf(node) {
  return [node.textContent, ...node.children.map(textOf)].join(" ");
}

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300, status,
    async json() { return body; },
  };
}

function resolvedBody(filename = NAME) {
  return {
    ok: true,
    followup: {
      contract_version: "claw-conversation-artifact-followup.v1",
      status: "resolved",
      source_artifact_id: DOC, source_integrity_ref: SHA,
      source_run_ref: "web_p01_run_1",
      source_filename: filename,
      choices: [],
      read_grant_issued: false, source_material_loaded: false,
      memory_restored: false, provider_write_authorized: false,
    },
  };
}

function choicesBody(names = [NAME, NAME]) {
  return {
    ok: true,
    followup: {
      contract_version: "claw-conversation-artifact-followup.v1",
      status: "confirmation_required",
      source_artifact_id: null, source_integrity_ref: null,
      source_run_ref: null,
      choices: names.map((filename, index) => ({
        artifact_id: index === 0 ? DOC : OTHER_DOC,
        filename, ordinal: 2 - index,
        integrity_ref: index === 0 ? SHA : OTHER_SHA,
      })),
      read_grant_issued: false, source_material_loaded: false,
      memory_restored: false, provider_write_authorized: false,
    },
  };
}

function harness({ respond }) {
  const calls = [];
  const doc = fakeDocument();
  const host = fakeHost(doc);
  const client = moduleApi.init(host);
  assert.ok(client, "context module must initialize on a valid host");
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    return respond(url, options, calls.length);
  };
  return { calls, host, client, fetchImpl, doc };
}

function installFetch(fetchImpl) {
  const previous = global.fetch;
  global.fetch = fetchImpl;
  return () => { global.fetch = previous; };
}

async function settle() {
  for (let index = 0; index < 12; ++index) {
    await new Promise((resolve) => setImmediate(resolve));
  }
}

(async () => {
  // 1. A resolved completed artifact is shown with its exact verified name,
  //    the new-approval truth and NO file-read/grant action.
  {
    const lab = harness({ respond: async () => response(resolvedBody()) });
    const restore = installFetch(lab.fetchImpl);
    await lab.client.show(CHAT);
    await settle();
    restore();
    assert.equal(lab.host.hidden, false);
    assert.equal(lab.host.attributes["aria-label"], "이 대화의 완료된 작업 파일");
    assert.equal(lab.calls.length, 1, "Exactly one bounded owner-index GET");
    assert.match(lab.calls[0].url,
      /^\/api\/claw\/conversations\/chat_aaa+\/artifact-followup\?/);
    assert.match(lab.calls[0].url, /kind=xlsx/);
    assert.match(lab.calls[0].url, /selector=latest/);
    assert.equal(lab.calls[0].options.method, "GET");
    assert.equal(lab.calls[0].options.credentials, "same-origin");
    assert.equal(lab.calls[0].options.cache, "no-store");
    const text = textOf({ textContent: "", children: lab.host.children });
    assert.match(text, /완료된 XLSX 작업 결과/);
    assert.match(text, new RegExp(NAME.replace(".", "\\.")));
    assert.match(text, /별도의 읽기·쓰기 승인이 필요/);
    assert.equal(lab.client.getState().status, "resolved");
    assert.equal(lab.client.getState().hidden, false);
    assert.equal(
      lab.host.children.some((node) => node.tag === "a"),
      false, "A reference never becomes a download link");
  }

  // 2. A resolved reference without a display name is still shown honestly.
  {
    const lab = harness({
      respond: async () => {
        const body = resolvedBody();
        delete body.followup.source_filename;
        return response(body);
      },
    });
    const restore = installFetch(lab.fetchImpl);
    await lab.client.show(CHAT);
    await settle();
    restore();
    assert.equal(lab.host.hidden, false);
    assert.match(textOf({ textContent: "", children: lab.host.children }),
      /표시 이름 없음/);
  }

  // 3. Two same-name completed files are never guessed: both are offered and
  //    the exact id+digest is re-verified only after an explicit user pick.
  {
    let phase = "list";
    const lab = harness({
      respond: async (url) => {
        if (url.includes("selector=exact")) {
          if (!url.includes(DOC) || !url.includes(SHA)) {
            throw new Error("UNEXPECTED_SELECTION " + url);
          }
          phase = "picked";
          return response(resolvedBody());
        }
        return response(choicesBody());
      },
    });
    const restore = installFetch(lab.fetchImpl);
    await lab.client.show(CHAT);
    await settle();
    assert.equal(lab.calls.length, 1, "Listing must not auto-select");
    assert.equal(lab.client.getState().status, "confirmation_required");
    assert.equal(lab.client.getState().options, 2);
    const list = lab.host.children.find(
      (node) => node.tag === "ul" && node.className
        .includes("claw-conversation-artifact-choices"));
    assert.ok(list, "Ambiguous completed files require explicit choices");
    assert.equal(list.children.length, 2);
    await list.children[0].children[0].click();
    await settle();
    restore();
    assert.equal(phase, "picked");
    assert.equal(lab.calls.length, 2, "User pick re-verifies exactly once");
    assert.match(lab.calls[1].url, /selector=exact/);
    assert.match(lab.calls[1].url, new RegExp("artifact_id=" + DOC));
    assert.match(lab.calls[1].url, new RegExp("integrity_ref=" + SHA));
    assert.equal(lab.client.getState().status, "resolved");
    assert.match(textOf({ textContent: "", children: lab.host.children }),
      new RegExp(NAME.replace(".", "\\.")));
  }

  // 4. A mismatching "exact" response cannot replace the user's choice.
  {
    const lab = harness({
      respond: async (url) => url.includes("selector=exact")
        ? response(resolvedBody("someone-else.xlsx"))
        : response(choicesBody()),
    });
    const restore = installFetch(lab.fetchImpl);
    await lab.client.show(CHAT);
    await settle();
    const list = lab.host.children.find(
      (node) => node.tag === "ul" && node.className
        .includes("claw-conversation-artifact-choices"));
    await list.children[0].children[0].click();
    await settle();
    restore();
    assert.equal(lab.client.getState().status, "confirmation_required",
      "A non-matching exact readback never becomes the selected file");
    assert.equal(list.children[0].children[0].disabled, false);
  }

  // 5. Forged authority flags, oversized/duplicate choice sets and wrong
  //    contracts are refused before any render.
  {
    for (const mutate of [
      (body) => { body.followup.read_grant_issued = true; },
      (body) => { body.followup.source_material_loaded = true; },
      (body) => { body.followup.provider_write_authorized = true; },
      (body) => { body.followup.memory_restored = true; },
      (body) => { body.followup.contract_version = "claw-conversation-artifact-followup.v2"; },
      (body) => { body.followup.source_integrity_ref = "not-a-hash"; },
      (body) => { body.followup.source_filename = "../escape.xlsx"; },
      (body) => { body.ok = false; },
      (body) => {
        body.followup.status = "confirmation_required";
        body.followup.choices = Array.from({ length: 32 }, () => ({
          artifact_id: DOC, filename: NAME, ordinal: 1, integrity_ref: SHA,
        }));
      },
      (body) => {
        body.followup.status = "confirmation_required";
        body.followup.choices = [
          { artifact_id: DOC, filename: NAME, ordinal: 1, integrity_ref: SHA },
          { artifact_id: DOC, filename: NAME, ordinal: 2, integrity_ref: OTHER_SHA },
        ];
      },
    ]) {
      const lab = harness({
        respond: async () => {
          const body = resolvedBody();
          mutate(body);
          return response(body);
        },
      });
      const restore = installFetch(lab.fetchImpl);
      await lab.client.show(CHAT);
      await settle();
      restore();
      assert.equal(lab.host.hidden, true, "refused response stays hidden");
      assert.deepEqual(lab.host.children, []);
      assert.equal(lab.calls.length, 1);
    }
  }

  // 6. Unavailable index / not_available / invalid conversation never render.
  {
    const failing = harness({
      respond: async (url) => url.includes("selector=latest")
        ? response({ ok: false, error: { code: "artifact_index_read_failed" } }, 503)
        : response(resolvedBody()),
    });
    let restore = installFetch(failing.fetchImpl);
    await failing.client.show(CHAT);
    await settle();
    restore();
    assert.equal(failing.host.hidden, true);
    assert.equal(failing.client.getState().status, "unavailable");

    const empty = harness({
      respond: async () => response({
        ok: true,
        followup: {
          contract_version: "claw-conversation-artifact-followup.v1",
          status: "not_available",
          source_artifact_id: null, source_integrity_ref: null,
          source_run_ref: null, choices: [],
          read_grant_issued: false, source_material_loaded: false,
          memory_restored: false, provider_write_authorized: false,
        },
      }),
    });
    restore = installFetch(empty.fetchImpl);
    await empty.client.show(CHAT);
    await settle();
    restore();
    assert.equal(empty.host.hidden, true);
    assert.equal(empty.client.getState().status, "not_available");

    const invalid = harness({
      respond: async () => { throw new Error("MUST_NOT_FETCH"); },
    });
    restore = installFetch(invalid.fetchImpl);
    await invalid.client.show("not-a-conversation");
    await settle();
    restore();
    assert.equal(invalid.calls.length, 0);
    assert.equal(invalid.host.hidden, true);
  }

  // 7. Stale responses for a previous conversation never render after the
  //    user switched (owner scope stays attached to the current id).
  {
    const pending = [];
    const lab = harness({
      respond: async (url) => new Promise((resolve) => {
        pending.push({ url, resolve });
      }),
    });
    const restore = installFetch(lab.fetchImpl);
    const first = lab.client.show(CHAT);
    const second = lab.client.show(OTHER_CHAT);
    await settle();
    assert.equal(pending.length, 2);
    pending[1].resolve(response({
      ok: true,
      followup: {
        contract_version: "claw-conversation-artifact-followup.v1",
        status: "not_available", source_artifact_id: null,
        source_integrity_ref: null, source_run_ref: null, choices: [],
        read_grant_issued: false, source_material_loaded: false,
        memory_restored: false, provider_write_authorized: false,
      },
    }));
    await settle();
    pending[0].resolve(response(resolvedBody()));
    await settle();
    await Promise.all([first, second]);
    restore();
    assert.equal(lab.client.getState().conversationId, OTHER_CHAT);
    assert.equal(lab.host.hidden, true,
      "A slower earlier conversation must not repaint after a switch");
  }

  // 8. #3933: the follow-up action delegates the ALREADY VERIFIED identifiers
  //    to the shipped web Excel panel module. This module performs no network
  //    request, no byte read and no grant; with no such module it degrades to
  //    opening the existing panel only.
  {
    const panel = new FakeNode("details");
    const calls = [];
    const doc = fakeDocument({ panel });
    const host = fakeHost(doc);
    const client = moduleApi.init(host);
    const restore = installFetch(async (url, options) => {
      calls.push({ url, options });
      return response(resolvedBody());
    });
    await client.show(CHAT);
    await settle();
    const action = host.children.find((node) => node.tag === "button");
    assert.ok(action, "Verified context must offer the existing approval panel");
    assert.match(action.textContent, /이어서 작업/);
    assert.match(action.textContent, /새 읽기 승인 필요/);
    action.handlers.click();
    assert.equal(panel.open, true);
    assert.equal(panel.scrolled, true);
    assert.equal(calls.length, 1, "Opening the panel is not an approval call");
    assert.equal(action.disabled, false,
      "A missing panel module never leaves the action stuck disabled");
    client.clear();
    restore();
    assert.equal(host.hidden, true);
    assert.deepEqual(host.children, []);
    assert.equal(client.getState().status, "idle");
  }

  // 9. With the shipped panel module present the click is DELEGATED with the
  //    exact conversation + artifact identity and no additional call here.
  {
    const panel = new FakeNode("details");
    const calls = [];
    const doc = fakeDocument({ panel });
    const host = fakeHost(doc);
    const client = moduleApi.init(host);
    const delegated = [];
    let settleAdopt = null;
    global.window = {
      PadiemClawWebXlsxSources: {
        adoptFromArtifact(conversationId, artifactId, integrityRef) {
          delegated.push({ conversationId, artifactId, integrityRef });
          return new Promise((resolve) => { settleAdopt = resolve; });
        },
      },
    };
    const restore = installFetch(async (url, options) => {
      calls.push({ url, options });
      return response(resolvedBody());
    });
    try {
      await client.show(CHAT);
      await settle();
      const action = host.children.find((node) => node.tag === "button");
      action.handlers.click();
      await settle();
      assert.deepEqual(delegated, [{
        conversationId: CHAT, artifactId: DOC, integrityRef: SHA,
      }], "The panel receives only the already-verified identifiers");
      assert.equal(calls.length, 1,
        "Delegation adds no request to this read-only module");
      assert.equal(action.disabled, true,
        "The action stays disabled while the panel owns the transaction");
      settleAdopt(false);
      await settle();
      assert.equal(action.disabled, false,
        "A refused adopt must let the user retry honestly");
      assert.equal(panel.open, false, "A refused adopt opens nothing by itself");
    } finally {
      delete global.window;
      restore();
    }
  }

  // 10. A panel module without the adopt entry point is never assumed.
  {
    const panel = new FakeNode("details");
    const host = fakeHost(fakeDocument({ panel }));
    const client = moduleApi.init(host);
    const calls = [];
    global.window = { PadiemClawWebXlsxSources: Object.freeze({}) };
    const restore = installFetch(async (url, options) => {
      calls.push({ url, options });
      return response(resolvedBody());
    });
    try {
      await client.show(CHAT);
      await settle();
      const action = host.children.find((node) => node.tag === "button");
      action.handlers.click();
      await settle();
      assert.equal(panel.open, true,
        "An older panel build still opens instead of failing silently");
      assert.equal(calls.length, 1);
      assert.equal(action.disabled, false);
    } finally {
      delete global.window;
      restore();
    }
  }

  console.log("CONVERSATION_ARTIFACT_CONTEXT_OWNER_ONLY_GET=PASS");
  console.log("CONVERSATION_ARTIFACT_CONTEXT_NO_GUESS_AMBIGUOUS=PASS");
  console.log("CONVERSATION_ARTIFACT_CONTEXT_REFERENCE_NOT_GRANT=PASS");
  console.log("CONVERSATION_ARTIFACT_CONTEXT_NEW_APPROVAL_REQUIRED=PASS");
  console.log("CONVERSATION_ARTIFACT_CONTEXT_STALE_SWITCH_SAFE=PASS");
  console.log("CONVERSATION_ARTIFACT_CONTEXT_DELEGATED_ADOPT_NO_SINK=PASS");
})().catch((error) => { console.error(error); process.exitCode = 1; });
