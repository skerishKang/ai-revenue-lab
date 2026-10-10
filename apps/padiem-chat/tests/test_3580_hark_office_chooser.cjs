"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const { parseCandidates, initChooser } = require("../static/claw-office-chooser.js");
const RUN = "run_3580_owner_quote";
const TOKEN = "a".repeat(64);

function response() {
  return {
    ok: true, contract_version: "hark-office-owner-chooser.v1",
    run_id: RUN, metadata_only: true, read_authorized: false,
    requires_engine_approval: true,
    candidates: [{ filename: "quote.xls", kind: "xls", size_bytes: 770560,
                   candidate_ref: TOKEN }],
  };
}
test("only canonical bounded metadata is presented", () => {
  assert.equal(parseCandidates(response(), RUN).length, 1);
  for (const change of [
    { read_authorized: true },
    { metadata_only: false },
    { requires_engine_approval: false },
    { run_id: "another_run" },
    { candidates: [{ ...response().candidates[0], filename: "../secret.xls" }] },
    { candidates: [{ ...response().candidates[0], filename: "c:\\secret.xls" }] },
    { candidates: [{ ...response().candidates[0], size_bytes: 99999999 }] },
    { candidates: [{ ...response().candidates[0], candidate_ref: "unauthorized" }] },
  ]) {
    assert.equal(parseCandidates({ ...response(), ...change }, RUN), null);
  }
});

class Element {
  constructor() {
    this.children = []; this.handlers = {};
    this.hidden = false; this.disabled = false;
    this.textContent = ""; this.type = "";
  }
  addEventListener(name, fn) { this.handlers[name] = fn; }
  appendChild(el) { this.children.push(el); }
  replaceChildren(...elements) { this.children = elements; }
  async click() { if (this.handlers.click) await this.handlers.click(); }
}
const tick = () => new Promise((resolve) => setImmediate(resolve));

test("candidate pick -> exact existing Engine approve; no forged file authority", async () => {
  const names = [
    "clawOfficeChooser", "clawOfficeFind", "clawOfficeNotice",
    "clawOfficeCandidates", "clawOfficeDecision", "clawOfficeDecisionLabel",
    "clawOfficeApprove", "clawOfficeDeny",
  ];
  const elements = Object.fromEntries(names.map((name) => [name, new Element()]));
  const doc = { getElementById: (id) => elements[id], createElement: () => new Element() };
  global.window = {
    __padiemClawLocalHandoff: {
      getViewModel() {
        return { requiresLocalAccess: true, device: { usable: true },
                 identity: { runId: RUN } };
      },
    },
  };
  const calls = [];
  global.fetch = async (url, args) => {
    calls.push({ url, args });
    let body;
    if (url.includes("/candidates?")) body = response();
    else if (url.includes("/candidates/select")) {
      body = {
        ok: true, run_id: RUN, status: "awaiting_approval",
        approval_required: true, engine_run_id: "p01_3580_verified_pause",
        processing_started: false, file_read_authorized: false,
      };
    } else if (url === "/api/claw/approvals/decision") {
      body = { ok: true, result: { run_id: "p01_3580_verified_pause", status: "running" } };
    } else {
      throw new Error("unexpected URL");
    }
    return { ok: true, json: async () => body };
  };
  try {
    const view = initChooser(doc);
    await elements.clawOfficeFind.click(); await tick();
    assert.equal(elements.clawOfficeCandidates.children.length, 1);
    assert.equal(view.getState().hasCandidates, true);
    await elements.clawOfficeCandidates.children[0].children[0].click();
    await tick();
    assert.equal(elements.clawOfficeDecision.hidden, false);
    assert.equal(view.getState().approvalPending, true);
    assert.deepEqual(JSON.parse(calls[1].args.body), {
      run_id: RUN, candidate_ref: TOKEN,
    });
    await elements.clawOfficeApprove.click(); await tick();
    assert.deepEqual(JSON.parse(calls[2].args.body), {
      run_id: "p01_3580_verified_pause", decision: "approve",
    });
    assert.equal(view.getState().approvalPending, false);
    assert.match(elements.clawOfficeNotice.textContent, /Engine/);
  } finally {
    delete global.window;
    delete global.fetch;
  }
});

test("absent canonical connected run never calls backend", async () => {
  const names = [
    "clawOfficeChooser", "clawOfficeFind", "clawOfficeNotice",
    "clawOfficeCandidates", "clawOfficeDecision", "clawOfficeDecisionLabel",
    "clawOfficeApprove", "clawOfficeDeny",
  ];
  const elements = Object.fromEntries(names.map((name) => [name, new Element()]));
  global.window = {
    __padiemClawLocalHandoff: {
      getViewModel: () => ({ requiresLocalAccess: true, device: { usable: false },
                             identity: { runId: RUN } }),
    },
  };
  let calls = 0;
  global.fetch = () => { calls += 1; throw new Error("unexpected network"); };
  try {
    const doc = { getElementById: (id) => elements[id] };
    initChooser(doc);
    await elements.clawOfficeFind.click();
    assert.equal(calls, 0);
  } finally {
    delete global.window;
    delete global.fetch;
  }
});
