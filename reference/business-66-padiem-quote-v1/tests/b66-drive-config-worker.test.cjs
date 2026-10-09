/* #3871 — Cloudflare Pages `_worker.js` 의 B66 브라우저 Drive 설정 전달 경로 계약.
   승인된 공개 브라우저 값만 Pages 환경변수에서 읽어 정확한 경로로 제공하고,
   없거나 형식이 틀리면 빈 문자열로 fail-closed 한다. 자격증명·토큰은 절대 내보내지 않는다.

   실제 네트워크·Cloudflare·Google 호출은 없다(env.ASSETS 는 주입 스텁). */
const assert = require("node:assert");
const path = require("node:path");
const { pathToFileURL } = require("node:url");

const WORKER_PATH = path.join(__dirname, "..", "_worker.js");
const ORIGIN = "https://quick-quote-kr.pages.dev";
const VALID_CLIENT_ID = "1234567890-abcdefghijklmnop.apps.googleusercontent.com";
const VALID_PICKER_APP_ID = "1234567890";
const VALID_PICKER_KEY = "AIzaSyA-1234567890_abcdefghijklmnop";

let workerPromise = null;
function worker() {
  if (!workerPromise) workerPromise = import(pathToFileURL(WORKER_PATH).href).then((mod) => mod.default);
  return workerPromise;
}

async function call(pathname, options) {
  const opts = options || {};
  const assets = [];
  const upstream = [];
  const upstreamUrls = [];
  const env = Object.assign({}, opts.env || {}, {
    ASSETS: {
      async fetch(request) {
        assets.push(new URL(request.url).pathname);
        return new Response("<html><body>asset</body></html>", {
          status: 200,
          headers: { "Content-Type": "text/html; charset=utf-8" }
        });
      }
    },
    /* PADIEM 브리지가 외부 네트워크로 나가지 않도록 바인딩을 주입한다. */
    PADIEM_CHAT_SERVICE: {
      async fetch(request) {
        upstream.push(new URL(request.url).pathname);
        upstreamUrls.push(request.url);
        return new Response(JSON.stringify({ ok: true }), {
          status: 200,
          headers: { "Content-Type": "application/json; charset=utf-8" }
        });
      }
    }
  });
  const method = opts.method || "GET";
  const request = new Request(ORIGIN + pathname, { method: method });
  const response = await (await worker()).fetch(request, env);
  const body = method === "HEAD" ? "" : await response.text();
  return { response, body, assets, upstream, upstreamUrls };
}

function headerValue(response, name) {
  return response.headers.get(name);
}

(async () => {
  /* ── 1. 승인된 값이 있으면 그대로 전달한다 ── */
  {
    const result = await call("/drive-config.js", {
      env: {
        B66_DRIVE_CLIENT_ID: VALID_CLIENT_ID,
        B66_DRIVE_PICKER_APP_ID: VALID_PICKER_APP_ID,
        B66_DRIVE_PICKER_DEVELOPER_KEY: VALID_PICKER_KEY
      }
    });
    assert.equal(result.response.status, 200, "VALID_ENV_STATUS");
    assert.equal(headerValue(result.response, "content-type"), "application/javascript; charset=utf-8",
      "VALID_ENV_CONTENT_TYPE");
    assert.equal(headerValue(result.response, "cache-control"), "no-store", "VALID_ENV_NO_STORE");
    assert.equal(headerValue(result.response, "x-content-type-options"), "nosniff", "VALID_ENV_NOSNIFF");
    assert.ok(result.body.includes('window.B66_DRIVE_CLIENT_ID = "' + VALID_CLIENT_ID + '";'),
      "VALID_ENV_CLIENT_ID_DELIVERED");
    assert.ok(result.body.includes('window.B66_DRIVE_PICKER_APP_ID = "' + VALID_PICKER_APP_ID + '";'),
      "VALID_ENV_PICKER_APP_ID_DELIVERED");
    assert.ok(result.body.includes('window.B66_DRIVE_PICKER_DEVELOPER_KEY = "' + VALID_PICKER_KEY + '";'),
      "VALID_ENV_PICKER_KEY_DELIVERED");
    assert.deepEqual(result.assets, [], "CONFIG_PATH_DOES_NOT_HIT_ASSETS");
  }

  /* ── 2. 설정이 없으면 전부 빈 문자열(fail-closed) ── */
  for (const env of [{}, { B66_DRIVE_CLIENT_ID: "" }, { B66_DRIVE_CLIENT_ID: "   " }]) {
    const result = await call("/drive-config.js", { env: env });
    assert.equal(result.response.status, 200, "EMPTY_ENV_STATUS");
    assert.ok(result.body.includes('window.B66_DRIVE_CLIENT_ID = "";'), "EMPTY_ENV_CLIENT_ID_BLANK");
    assert.ok(result.body.includes('window.B66_DRIVE_PICKER_APP_ID = "";'), "EMPTY_ENV_PICKER_APP_ID_BLANK");
    assert.ok(result.body.includes('window.B66_DRIVE_PICKER_DEVELOPER_KEY = "";'),
      "EMPTY_ENV_PICKER_KEY_BLANK");
  }

  /* ── 3. 잘못된 클라이언트 ID 는 빈 문자열 ── */
  const badClientIds = [
    "not-a-client-id",
    "foo.example.com",
    "a.apps.googleusercontent.com.evil.com",
    "short.apps.googleusercontent.com",
    "x".repeat(300) + ".apps.googleusercontent.com",
    "<script>alert(1)</script>",
    "a\";alert(1);//.apps.googleusercontent.com"
  ];
  for (const value of badClientIds) {
    const result = await call("/drive-config.js", { env: { B66_DRIVE_CLIENT_ID: value } });
    assert.ok(result.body.includes('window.B66_DRIVE_CLIENT_ID = "";'),
      "MALFORMED_CLIENT_ID_BLANKED: " + value.slice(0, 40));
    assert.equal(result.body.includes("<script"), false, "MALFORMED_NO_SCRIPT_INJECTION");
    assert.equal(result.body.includes(">"), false, "MALFORMED_NO_ANGLE_BRACKET");
    assert.equal(result.body.includes(value.slice(0, 10) + ";"), false, "MALFORMED_VALUE_NOT_EMITTED");
  }

  /* ── 3b. 앞뒤 공백은 정리해서 받아들인다(값 자체는 유효) ── */
  {
    const result = await call("/drive-config.js", {
      env: { B66_DRIVE_CLIENT_ID: "  " + VALID_CLIENT_ID + "  " }
    });
    assert.ok(result.body.includes('window.B66_DRIVE_CLIENT_ID = "' + VALID_CLIENT_ID + '";'),
      "PADDED_VALID_CLIENT_ID_TRIMMED");
  }

  /* ── 4. 잘못된 Picker 값도 빈 문자열 ── */
  {
    const result = await call("/drive-config.js", {
      env: {
        B66_DRIVE_CLIENT_ID: VALID_CLIENT_ID,
        B66_DRIVE_PICKER_APP_ID: "not-a-number",
        B66_DRIVE_PICKER_DEVELOPER_KEY: "AIza\"><script>alert(1)</script>"
      }
    });
    assert.ok(result.body.includes('window.B66_DRIVE_CLIENT_ID = "' + VALID_CLIENT_ID + '";'),
      "BAD_PICKER_KEEPS_CLIENT_ID");
    assert.ok(result.body.includes('window.B66_DRIVE_PICKER_APP_ID = "";'), "BAD_PICKER_APP_ID_BLANKED");
    assert.ok(result.body.includes('window.B66_DRIVE_PICKER_DEVELOPER_KEY = "";'), "BAD_PICKER_KEY_BLANKED");
    assert.equal(result.body.includes("<script"), false, "BAD_PICKER_NO_INJECTION");
  }

  /* ── 5. 비문자열/거대값 환경변수는 무시한다 ── */
  {
    const result = await call("/drive-config.js", {
      env: {
        B66_DRIVE_CLIENT_ID: 12345,
        B66_DRIVE_PICKER_APP_ID: { toString: () => "1234567890" },
        B66_DRIVE_PICKER_DEVELOPER_KEY: "x".repeat(600)
      }
    });
    assert.ok(result.body.includes('window.B66_DRIVE_CLIENT_ID = "";'), "NON_STRING_CLIENT_ID_IGNORED");
    assert.ok(result.body.includes('window.B66_DRIVE_PICKER_APP_ID = "";'), "NON_STRING_APP_ID_IGNORED");
    assert.ok(result.body.includes('window.B66_DRIVE_PICKER_DEVELOPER_KEY = "";'), "OVERSIZED_KEY_IGNORED");
  }

  /* ── 6. HEAD 는 같은 헤더, 빈 본문 ── */
  {
    const result = await call("/drive-config.js", {
      method: "HEAD",
      env: { B66_DRIVE_CLIENT_ID: VALID_CLIENT_ID }
    });
    assert.equal(result.response.status, 200, "HEAD_STATUS");
    assert.equal(headerValue(result.response, "content-type"), "application/javascript; charset=utf-8",
      "HEAD_CONTENT_TYPE");
    assert.equal(headerValue(result.response, "cache-control"), "no-store", "HEAD_NO_STORE");
    assert.equal(result.body, "", "HEAD_EMPTY_BODY");
    assert.deepEqual(result.assets, [], "HEAD_DOES_NOT_HIT_ASSETS");
  }

  /* ── 7. GET/HEAD 외 메서드는 405, 값이 새지 않는다 ── */
  for (const method of ["POST", "PUT", "DELETE", "PATCH"]) {
    const result = await call("/drive-config.js", {
      method: method,
      env: { B66_DRIVE_CLIENT_ID: VALID_CLIENT_ID, B66_DRIVE_PICKER_DEVELOPER_KEY: VALID_PICKER_KEY }
    });
    assert.equal(result.response.status, 405, "METHOD_NOT_ALLOWED_STATUS: " + method);
    assert.equal(headerValue(result.response, "allow"), "GET, HEAD", "METHOD_ALLOW_HEADER: " + method);
    assert.equal(result.body.indexOf(VALID_CLIENT_ID), -1, "NO_CLIENT_ID_LEAK_IN_ERROR: " + method);
    assert.equal(result.body.indexOf(VALID_PICKER_KEY), -1, "NO_PICKER_KEY_LEAK_IN_ERROR: " + method);
    result.response.headers.forEach((value) => {
      assert.equal(String(value).indexOf(VALID_CLIENT_ID), -1, "NO_CLIENT_ID_LEAK_IN_HEADER: " + method);
      assert.equal(String(value).indexOf(VALID_PICKER_KEY), -1, "NO_PICKER_KEY_LEAK_IN_HEADER: " + method);
    });
    assert.deepEqual(result.assets, [], "METHOD_NOT_ALLOWED_DOES_NOT_HIT_ASSETS: " + method);
  }

  /* ── 8. 정확한 경로가 아니면 기존 자산 경로로 넘어간다 ── */
  for (const pathname of ["/drive-config.js.map", "/sub/drive-config.js", "/drive-config.js/extra", "/drive-config"]) {
    const result = await call(pathname, { env: { B66_DRIVE_CLIENT_ID: VALID_CLIENT_ID } });
    assert.deepEqual(result.assets, [pathname], "NON_MATCHING_PATH_FALLS_THROUGH: " + pathname);
    assert.equal(result.body.indexOf(VALID_CLIENT_ID), -1, "NON_MATCHING_PATH_NO_CONFIG_BODY: " + pathname);
  }

  /* ── 9. 설정이 있어도 문서 자산은 변형되지 않는다 ── */
  {
    const result = await call("/", { env: { B66_DRIVE_CLIENT_ID: VALID_CLIENT_ID } });
    assert.deepEqual(result.assets, ["/"], "DOCUMENT_STILL_SERVED_FROM_ASSETS");
    assert.equal(result.body, "<html><body>asset</body></html>", "ASSET_BODY_UNCHANGED_WITH_CONFIG");
    assert.equal(result.body.indexOf(VALID_CLIENT_ID), -1, "ASSET_BODY_HAS_NO_INJECTED_CONFIG");
  }
  {
    const result = await call("/index.html", { env: {} });
    assert.deepEqual(result.assets, ["/index.html"], "INDEX_SERVED_FROM_ASSETS_WITHOUT_CONFIG");
    assert.equal(result.body, "<html><body>asset</body></html>", "ASSET_BODY_UNCHANGED_WITHOUT_CONFIG");
  }

  /* ── 10. 기존 경로는 그대로다 ── */
  {
    const intake = await call("/api/v1/quote/intake", { method: "POST", env: {} });
    assert.equal(intake.response.status, 410, "INTAKE_STILL_DISABLED");
    assert.deepEqual(intake.assets, [], "INTAKE_DOES_NOT_HIT_ASSETS");
  }
  {
    const unknown = await call("/api/padiem/not-a-route", { env: {} });
    assert.equal(unknown.response.status, 404, "PADIEM_UNKNOWN_ROUTE_STILL_404");
    assert.deepEqual(unknown.assets, [], "PADIEM_ROUTE_DOES_NOT_HIT_ASSETS");
    assert.ok(unknown.body.includes("padiem_route_not_allowed"), "PADIEM_ROUTE_CODE_UNCHANGED");
  }
  {
    /* 기존 PADIEM 브리지는 그대로 동작한다(설정 경로 추가가 라우팅을 바꾸지 않는다). */
    const bridged = await call("/api/padiem/b66/quote/models", { env: { B66_DRIVE_CLIENT_ID: VALID_CLIENT_ID } });
    assert.equal(bridged.response.status, 200, "PADIEM_BRIDGE_STILL_WORKS");
    assert.deepEqual(bridged.upstream, ["/api/b66/quote/models"], "PADIEM_UPSTREAM_PATH_UNCHANGED");
    assert.deepEqual(bridged.assets, [], "PADIEM_BRIDGE_DOES_NOT_HIT_ASSETS");
    assert.equal(bridged.body.indexOf(VALID_CLIENT_ID), -1, "PADIEM_BRIDGE_HAS_NO_CONFIG_LEAK");
  }

  /* ── 10b. OAuth 콜백 쿼리(state/code)가 프록시에서 조용히 버려지지 않는다 ──
     쿼리를 떨어뜨리면 백엔드가 query_state=None 으로 보고 invalid_oauth_state 를 반환한다. */
  {
    const state = "state-token-abc123";
    const code = "4/0AX-example-code";
    const callback = await call("/api/padiem/auth/google/callback?state=" + state + "&code=" + code);
    assert.equal(callback.response.status, 200, "OAUTH_CALLBACK_PROXIED");
    assert.deepEqual(callback.upstream, ["/auth/google/callback"], "OAUTH_CALLBACK_UPSTREAM_PATH");
    const upstreamUrl = new URL(callback.upstreamUrls[0]);
    assert.equal(upstreamUrl.searchParams.get("state"), state, "OAUTH_CALLBACK_STATE_FORWARDED");
    assert.equal(upstreamUrl.searchParams.get("code"), code, "OAUTH_CALLBACK_CODE_FORWARDED");
  }

  /* ── 11. 생성된 설정 파일은 정적 폴백과 같은 전역 이름을 쓴다 ── */
  {
    const fs = require("node:fs");
    const staticConfig = fs.readFileSync(path.join(__dirname, "..", "drive-config.js"), "utf8");
    const result = await call("/drive-config.js", { env: { B66_DRIVE_CLIENT_ID: VALID_CLIENT_ID } });
    ["B66_DRIVE_CLIENT_ID", "B66_DRIVE_PICKER_APP_ID", "B66_DRIVE_PICKER_DEVELOPER_KEY"].forEach((name) => {
      assert.ok(result.body.includes("window." + name + " ="), "WORKER_EMITS_GLOBAL: " + name);
      assert.ok(staticConfig.includes('"' + name + '"'), "STATIC_FALLBACK_DECLARES_GLOBAL: " + name);
    });
  }

  console.log("B66_DRIVE_CONFIG_WORKER=PASS");
  console.log("VALID_ENV_DELIVERED=PASS");
  console.log("EMPTY_ENV_FAILS_CLOSED=PASS");
  console.log("MALFORMED_CLIENT_ID_BLOCKED=PASS");
  console.log("MALICIOUS_VALUE_INJECTION_BLOCKED=PASS");
  console.log("HEAD_SUPPORTED=PASS");
  console.log("NON_GET_HEAD_REJECTED_WITHOUT_LEAK=PASS");
  console.log("EXACT_PATH_ONLY=PASS");
  console.log("EXACT_ASSET_UNCHANGED=PASS");
  console.log("EXISTING_ROUTES_UNCHANGED=PASS");
  console.log("OAUTH_CALLBACK_QUERY_FORWARDED=PASS");
})().catch((error) => {
  console.error("B66_DRIVE_CONFIG_WORKER=FAIL");
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
