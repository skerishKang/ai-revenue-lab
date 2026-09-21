import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import {
  handleCaller,
  PREVIEW_PILOT_PATH,
  ENGINE_SKILL_RUN_URL,
  PREVIEW_PILOT_APP_ID,
  SYNTHETIC_TASK_PAYLOAD,
} from "../worker.mjs";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const PILOT_RUNNER_SECRET = "r".repeat(64);
const PREVIEW_CREDENTIAL = "c".repeat(64);
const PREVIEW_CALLER_ID = "preview-pilot-caller";

function validRequest(token = PILOT_RUNNER_SECRET) {
  return new Request(`https://caller.example${PREVIEW_PILOT_PATH}`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ ignore_me: true }),
  });
}

function fakeEnv(opts = {}) {
  const calls = [];
  const {
    runnerSecret = PILOT_RUNNER_SECRET,
    callerId = PREVIEW_CALLER_ID,
    credential = PREVIEW_CREDENTIAL,
    engineResponse = new Response(
      JSON.stringify({
        ok: true,
        agent_skill: {
          execution_state: "completed",
          resolved_tool_ids: ["a5-agent-probe.tool"],
        },
      }),
      { status: 200, headers: { "content-type": "application/json" } }
    ),
    engineFetch,
  } = opts;

  const fetchImpl = async (request) => {
    calls.push(request);
    return engineFetch ? engineFetch(request) : engineResponse;
  };

  const env = {
    PILOT_RUNNER_SECRET: runnerSecret,
    PREVIEW_ENGINE_CALLER_ID: callerId,
    PREVIEW_ENGINE_CREDENTIAL: credential,
    PREVIEW_ENGINE: { fetch: fetchImpl },
  };

  return { calls, env };
}

test("1. valid runner token invokes PREVIEW_ENGINE with synthetic payload and caller headers", async () => {
  const { calls, env } = fakeEnv();
  const response = await handleCaller(validRequest(), env);

  assert.equal(response.status, 200);
  const data = await response.json();
  assert.equal(data.ok, true);
  assert.equal(data.target_service, "padiem-ai-engine-preview");
  assert.equal(data.synthetic_app_id, PREVIEW_PILOT_APP_ID);
  assert.equal(data.engine_response.agent_skill.execution_state, "completed");

  assert.equal(calls.length, 1);
  const engineReq = calls[0];
  assert.equal(engineReq.url, ENGINE_SKILL_RUN_URL);
  assert.equal(engineReq.method, "POST");
  assert.equal(engineReq.headers.get("x-padiem-engine-caller"), PREVIEW_CALLER_ID);
  assert.equal(engineReq.headers.get("x-padiem-engine-credential"), PREVIEW_CREDENTIAL);

  const sentBody = await engineReq.json();
  assert.deepEqual(sentBody, SYNTHETIC_TASK_PAYLOAD);
  assert.equal(sentBody.app_id, PREVIEW_PILOT_APP_ID);
});

test("2. missing or invalid runner token fails closed with 401", async () => {
  const { calls, env } = fakeEnv();

  // No auth header
  const reqNoAuth = new Request(`https://caller.example${PREVIEW_PILOT_PATH}`, { method: "POST" });
  const resNoAuth = await handleCaller(reqNoAuth, env);
  assert.equal(resNoAuth.status, 401);
  assert.equal(calls.length, 0);

  // Wrong token
  const reqWrong = validRequest("wrong-token");
  const resWrong = await handleCaller(reqWrong, env);
  assert.equal(resWrong.status, 401);
  assert.equal(calls.length, 0);
});

test("3. missing PREVIEW_ENGINE service binding fails closed with 503", async () => {
  const { env } = fakeEnv();
  delete env.PREVIEW_ENGINE;

  const response = await handleCaller(validRequest(), env);
  assert.equal(response.status, 503);
  const data = await response.json();
  assert.equal(data.error.code, "service_binding_unavailable");
});

test("4. missing PREVIEW_ENGINE_CREDENTIAL fails closed with 503", async () => {
  const { env } = fakeEnv();
  delete env.PREVIEW_ENGINE_CREDENTIAL;

  const response = await handleCaller(validRequest(), env);
  assert.equal(response.status, 503);
  const data = await response.json();
  assert.equal(data.error.code, "caller_credential_unavailable");
});

test("5. GET /health returns 200 ready", async () => {
  const { env } = fakeEnv();
  const req = new Request("https://caller.example/health", { method: "GET" });
  const res = await handleCaller(req, env);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.status, "ready");
});

test("6. engine network/binding failure returns 502 fail-closed", async () => {
  const { env } = fakeEnv({
    engineFetch: async () => {
      throw new Error("RPC failure");
    },
  });

  const response = await handleCaller(validRequest(), env);
  assert.equal(response.status, 502);
  const data = await response.json();
  assert.equal(data.error.code, "engine_connection_failed");
});

test("7. wrangler.toml isolation guarantees", () => {
  const wranglerPath = join(__dirname, "..", "wrangler.toml");
  const content = readFileSync(wranglerPath, "utf-8");

  assert.match(content, /name\s*=\s*"padiem-ai-engine-preview-caller"/);
  assert.match(content, /service\s*=\s*"padiem-ai-engine-preview"/);
  assert.equal(content.includes('service = "padiem-ai-engine"'), false);
  assert.equal(content.includes("d1_databases"), false);
  assert.equal(content.includes("B14_SERVICE"), false);
  assert.equal(content.includes("CONTROL_PLANE"), false);
});
