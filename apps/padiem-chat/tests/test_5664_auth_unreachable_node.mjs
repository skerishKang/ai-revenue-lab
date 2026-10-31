"use strict";
/* #5664: the shipped auth POST path under a platform-level failure.
 *
 * The Chat Python Worker can fail isolate startup with
 * `NoGilError: Attempted to use PyProxy when Python GIL not held`
 * (cloudflare/workerd#6624) and then answer a plain-text 5xx that no route
 * produced. That body is not a verdict about the account:
 *
 *   1. it must not be reported as a rejected credential,
 *   2. the reset confirm may replay it exactly once (its one-time token makes
 *      the replay apply at most once), and every other auth write may not,
 *   3. a route answer is final in both directions,
 *   4. a 2xx that carries no route answer must never be read as success.
 *
 * The evaluated function is the shipped `static/app.js` bytes. Only `fetch`,
 * the delay clock and the locale lookup are stubs.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const STATIC = join(fileURLToPath(new URL(".", import.meta.url)), "..", "static");
const APP = readFileSync(join(STATIC, "app.js"), "utf8");
const LOCALE = readFileSync(join(STATIC, "locale.js"), "utf8");

function blockEnd(source, openIndex) {
  let depth = 0;
  for (let index = openIndex; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    else if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) return index + 1;
    }
  }
  throw new Error("unbalanced block in app.js");
}

function shippedRequest() {
  const start = APP.indexOf("const AUTH_SERVER_UNREACHABLE");
  assert.ok(start >= 0, "the auth transport constants are missing from app.js");
  const fnStart = APP.indexOf("async function passwordAuthRequest(", start);
  assert.ok(fnStart > start, "passwordAuthRequest is missing from app.js");
  const open = APP.indexOf(") {", fnStart) + 2;
  const block = APP.slice(start, blockEnd(APP, open));
  // The block runs in a bare context that holds only the three names it may
  // use; the completion value names the shipped function.
  return (uiT, fetch, setTimeoutStub) =>
    vm.runInNewContext(`${block}\npasswordAuthRequest;`, { uiT, fetch, setTimeout: setTimeoutStub }, {
      filename: "static/app.js#passwordAuthRequest",
    });
}

function localeValue(key) {
  // The file holds two ko/en pairs (labels, then promptCopy); read the labels one.
  const labels = LOCALE.split("const promptCopy", 1)[0];
  const parts = labels.split("\n    en: {");
  assert.equal(parts.length, 2, "the ko/en label blocks are missing");
  const read = (block) => {
    const match = new RegExp(`"${key}":\\s*"([^"]+)"`).exec(block);
    assert.ok(match, `${key} is missing from a locale block`);
    return match[1];
  };
  return { ko: read(parts[0]), en: read(parts[1]) };
}

const UNREACHABLE = localeValue("auth-server-unreachable");
const GENERIC = localeValue("auth-error-generic");
const UNREACHABLE_COPY = {
  "auth-server-unreachable": UNREACHABLE,
  "auth-error-generic": GENERIC,
};

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: async () => body };
}

function plainResponse(status) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      throw new SyntaxError("Unexpected token e in JSON");
    },
  };
}

function scripted(responses) {
  const calls = [];
  const fetch = async (path, init) => {
    calls.push({ path, body: init && init.body });
    return responses[Math.min(calls.length - 1, responses.length - 1)];
  };
  return { fetch, calls };
}

function runner(responses) {
  const { fetch, calls } = scripted(responses);
  const delays = [];
  const setTimeoutStub = (resolve, milliseconds) => {
    delays.push(milliseconds);
    resolve();
  };
  const uiT = (key) => {
    assert.ok(key in UNREACHABLE_COPY, `unexpected locale key ${key}`);
    return UNREACHABLE_COPY[key].ko;
  };
  const request = shippedRequest()(uiT, fetch, setTimeoutStub);
  const call = (options) =>
    request(
      "/api/auth/password/reset/confirm",
      { token: "tok-value", new_password: "a-new-secret" },
      options,
    );
  return { call, calls, delays };
}

test("a plain-text 5xx is not reported as a rejected credential", async () => {
  const { call, calls } = runner([plainResponse(500)]);
  await assert.rejects(call(), (error) => {
    assert.equal(error.code, "auth_server_unreachable");
    assert.equal(error.message, UNREACHABLE.ko);
    assert.notEqual(error.message, GENERIC.ko);
    return true;
  });
  assert.equal(calls.length, 1, "a single attempt is the default");
});

test("the reset confirm replays a platform failure exactly once", async () => {
  const { call, calls, delays } = runner([plainResponse(500)]);
  await assert.rejects(call({ retryUnreachable: true }), (error) => {
    assert.equal(error.code, "auth_server_unreachable");
    assert.equal(error.message, UNREACHABLE.ko);
    return true;
  });
  assert.equal(calls.length, 2, "one replay, never a loop");
  assert.deepEqual(delays, [600], "the replay waits once before it re-sends");
  assert.equal(calls[0].body, calls[1].body, "the replay re-sends the same body");
});

test("the replay recovers the request when the next attempt answers", async () => {
  const { call, calls } = runner([plainResponse(500), jsonResponse(200, { ok: true })]);
  assert.deepEqual(await call({ retryUnreachable: true }), { ok: true });
  assert.equal(calls.length, 2);
});

test("a route refusal is final and never replayed", async () => {
  const refusal = {
    error: { code: "password_reset_token_invalid", message: "재설정 링크가 올바르지 않습니다." },
  };
  const { call, calls } = runner([jsonResponse(400, refusal)]);
  await assert.rejects(call({ retryUnreachable: true }), (error) => {
    assert.equal(error.code, "password_reset_token_invalid");
    assert.equal(error.message, refusal.error.message);
    assert.notEqual(error.code, "auth_server_unreachable");
    return true;
  });
  assert.equal(calls.length, 1, "an application answer must not be replayed");
});

test("a rejected credential keeps the server's own answer", async () => {
  const refusal = {
    error: { code: "invalid_credentials", message: "이메일 또는 비밀번호가 올바르지 않습니다." },
  };
  const { call, calls } = runner([jsonResponse(401, refusal)]);
  await assert.rejects(call(), (error) => {
    assert.equal(error.code, "invalid_credentials");
    assert.equal(error.message, refusal.error.message);
    return true;
  });
  assert.equal(calls.length, 1);
});

test("a 2xx without a route answer is never treated as success", async () => {
  const { call, calls } = runner([plainResponse(200)]);
  await assert.rejects(call({ retryUnreachable: true }), (error) => {
    assert.equal(error.code, "auth_server_unreachable");
    assert.equal(error.message, UNREACHABLE.ko);
    return true;
  });
  assert.equal(calls.length, 1, "a 2xx is never replayed");
});

test("the unreachable copy is its own message in both locales", () => {
  for (const language of ["ko", "en"]) {
    assert.ok(UNREACHABLE[language]);
    assert.notEqual(UNREACHABLE[language], GENERIC[language]);
  }
});
