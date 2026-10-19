"use strict";
const assert = require("node:assert/strict");
const shared = require("../shared-answer-copy.js");
assert.equal(shared.VERSION, "shared-answer-copy-v1");

/* Modern path: navigator.clipboard.writeText resolves -> true. */
(async () => {
  let wrote = null;
  Object.defineProperty(globalThis, "navigator", {
    value: { clipboard: { writeText: (value) => { wrote = value; return Promise.resolve(); } } },
    configurable: true
  });
  assert.equal(await shared.copyText("견적 답변"), true);
  assert.equal(wrote, "견적 답변");

  /* Provider rejection -> false, never throws. */
  Object.defineProperty(globalThis, "navigator", {
    value: { clipboard: { writeText: () => Promise.reject(new Error("denied")) } },
    configurable: true
  });
  assert.equal(await shared.copyText("x"), false);

  Object.defineProperty(globalThis, "navigator", {
    value: { clipboard: { writeText: () => { throw new Error("sync denied"); } } },
    configurable: true
  });
  assert.equal(await shared.copyText("sync"), false);

  /* Legacy path: textarea + execCommand fallback. */
  const field = { value: "", select() {}, remove() {} };
  Object.defineProperty(globalThis, "navigator", {
    value: { clipboard: null }, configurable: true
  });
  globalThis.document = {
    createElement: () => field,
    execCommand: (name) => name === "copy",
    body: { appendChild() {} }
  };
  assert.equal(await shared.copyText("legacy"), true);
  assert.equal(field.value, "legacy");

  /* No clipboard surface at all -> false. */
  globalThis.document = {
    createElement: () => { throw new Error("no dom"); },
    execCommand: () => true,
    body: { appendChild() {} }
  };
  assert.equal(await shared.copyText("none"), false);

  console.log("SHARED_CHAT_CLAW_B66_ANSWER_COPY=PASS");
})();
