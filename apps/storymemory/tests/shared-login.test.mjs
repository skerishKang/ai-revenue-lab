import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createStoryMemorySharedAuth, STORYMEMORY_AUTH_CALLBACK_URI, STORYMEMORY_AUTH_CLIENT_ID } from "../public/storymemory-shared-auth.mjs";
import { initializeStoryMemorySharedAuth } from "../public/storymemory-shared-auth-ui.mjs";

const now = 1_800_000_000;
const bytesToB64url = (bytes) => Buffer.from(bytes).toString("base64url");
const json64 = (value) => bytesToB64url(Buffer.from(JSON.stringify(value), "utf8"));

async function signedAccessToken(key, kid = "storymemory-test-kid", at = now) {
  const input = json64({ alg: "ES256", typ: "JWT", kid }) + "." + json64({
    iss: "https://auth.padiem.net",
    aud: STORYMEMORY_AUTH_CLIENT_ID,
    sub: "sub_test-account",
    account_id: "sub_test-account",
    sid: "A".repeat(32),
    iat: at,
    exp: at + 900,
    token_use: "access"
  });
  const signature = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, Buffer.from(input));
  return input + "." + bytesToB64url(signature);
}

async function configuredFixture() {
  const pair = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
  const privateJwk = await crypto.subtle.exportKey("jwk", pair.privateKey);
  const publicJwk = { ...(await crypto.subtle.exportKey("jwk", pair.publicKey)), kid: "storymemory-test-kid", use: "sig", alg: "ES256" };
  const stateKey = bytesToB64url(crypto.getRandomValues(new Uint8Array(32)));
  const env = {
    STORYMEMORY_SHARED_AUTH_ENABLED: "true",
    STORYMEMORY_AUTH_CLIENT_KID: "storymemory-test-kid",
    STORYMEMORY_AUTH_CLIENT_PRIVATE_JWK: JSON.stringify(privateJwk),
    STORYMEMORY_AUTH_STATE_KEY: stateKey
  };
  const accessToken = await signedAccessToken(pair.privateKey);
  const expiredAccessToken = await signedAccessToken(pair.privateKey, "storymemory-test-kid", now - 901);
  const calls = [];
  const fetcher = async (url, options = {}) => {
    calls.push({ url: String(url), options });
    if (String(url) === "https://auth.padiem.net/.well-known/jwks.json") {
      return Response.json({ keys: [publicJwk] });
    }
    if (String(url) === "https://auth.padiem.net/token") {
      return Response.json({ access_token: accessToken, refresh_token: "opaque-refresh-for-test", token_type: "Bearer", expires_in: 900 });
    }
    if (String(url) === "https://auth.padiem.net/logout") return Response.json({ ok: true });
    throw new Error("unexpected_auth_endpoint");
  };
  return { env, fetcher, calls, accessToken, expiredAccessToken, publicJwk };
}

function cookieValue(response, name) {
  const rows = response.headers.getSetCookie();
  const row = rows.find((value) => value.startsWith(name + "="));
  assert.ok(row, "expected auth cookie");
  return row.slice(name.length + 1, row.indexOf(";"));
}

test("disabled shared auth keeps the local-only status and does not contact padiem-auth", async () => {
  let networkCalls = 0;
  const handle = createStoryMemorySharedAuth({ fetcher: async () => { networkCalls++; throw new Error("unexpected"); }, now: () => now });
  const status = await handle(new Request("https://storymemory-padiem.pages.dev/auth/status"), {});
  assert.equal(status.status, 200);
  assert.deepEqual(await status.json(), { configured: false, authenticated: false, syncEnabled: false });
  const login = await handle(new Request("https://storymemory-padiem.pages.dev/auth/login"), {});
  assert.equal(login.status, 503);
  assert.equal(networkCalls, 0);
});

test("login state uses padiem-auth, callback sets host-only HttpOnly cookies, status reveals no token, logout revokes", async () => {
  const fixture = await configuredFixture();
  const handle = createStoryMemorySharedAuth({ fetcher: fixture.fetcher, now: () => now });

  const start = await handle(new Request("https://storymemory-padiem.pages.dev/auth/login?next=https%3A%2F%2Fevil.example%2F"), fixture.env);
  assert.equal(start.status, 302);
  const handoff = new URL(start.headers.get("location"));
  assert.equal(handoff.origin, "https://auth.padiem.net");
  assert.equal(handoff.pathname, "/login");
  assert.equal(handoff.searchParams.get("client_id"), STORYMEMORY_AUTH_CLIENT_ID);
  assert.equal(handoff.searchParams.get("redirect_uri"), STORYMEMORY_AUTH_CALLBACK_URI);
  assert.equal(handoff.searchParams.get("code_challenge_method"), "S256");
  const stateCookie = cookieValue(start, "__Host-storymemory-auth-state");
  const state = handoff.searchParams.get("state");

  const testCode = "A".repeat(32) + "." + "B".repeat(32);
  const callback = await handle(new Request("https://storymemory-padiem.pages.dev/auth/callback?code=" + testCode + "&state=" + encodeURIComponent(state), {
    headers: { cookie: "__Host-storymemory-auth-state=" + stateCookie }
  }), fixture.env);
  assert.equal(callback.status, 302);
  assert.equal(new URL(callback.headers.get("location")).href, "https://storymemory-padiem.pages.dev/");
  const callbackCookies = callback.headers.getSetCookie();
  assert.ok(callbackCookies.some((value) => value.startsWith("__Host-storymemory-access=") && value.includes("HttpOnly") && value.includes("Secure")));
  assert.ok(callbackCookies.some((value) => value.startsWith("storymemory_refresh=") && value.includes("HttpOnly") && value.includes("Path=/auth")));
  assert.ok(callbackCookies.some((value) => value.startsWith("__Host-storymemory-shared=1") && !value.includes("HttpOnly")));
  assert.ok(callbackCookies.some((value) => value.startsWith("__Host-storymemory-auth-state=") && value.includes("Max-Age=0")));
  assert.equal(await callback.text(), "");
  const exchange = fixture.calls.find((call) => call.url === "https://auth.padiem.net/token");
  const exchangeBody = new URLSearchParams(exchange.options.body);
  assert.equal(exchangeBody.get("grant_type"), "authorization_code");
  assert.equal(exchangeBody.get("code"), testCode);
  assert.equal(exchangeBody.get("redirect_uri"), STORYMEMORY_AUTH_CALLBACK_URI);
  const verifier = exchangeBody.get("code_verifier");
  const expectedChallenge = bytesToB64url(await crypto.subtle.digest("SHA-256", Buffer.from(verifier)));
  assert.equal(expectedChallenge, handoff.searchParams.get("code_challenge"));
  const assertion = exchangeBody.get("client_assertion").split(".");
  assert.equal(assertion.length, 3);
  assert.equal(JSON.parse(Buffer.from(assertion[0], "base64url").toString("utf8")).kid, "storymemory-test-kid");
  const clientClaims = JSON.parse(Buffer.from(assertion[1], "base64url").toString("utf8"));
  assert.equal(clientClaims.iss, STORYMEMORY_AUTH_CLIENT_ID);
  assert.equal(clientClaims.sub, STORYMEMORY_AUTH_CLIENT_ID);
  assert.equal(clientClaims.aud, "https://auth.padiem.net/token");
  const servicePublicKey = await crypto.subtle.importKey("jwk", fixture.publicJwk, { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
  assert.equal(await crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, servicePublicKey, Buffer.from(assertion[2], "base64url"), Buffer.from(assertion[0] + "." + assertion[1])), true);

  const session = await handle(new Request("https://storymemory-padiem.pages.dev/auth/status", {
    headers: { cookie: "__Host-storymemory-access=" + fixture.accessToken + "; storymemory_refresh=opaque-refresh-for-test" }
  }), fixture.env);
  assert.equal(session.status, 200);
  const body = await session.text();
  assert.deepEqual(JSON.parse(body), { configured: true, authenticated: true, syncEnabled: false });
  assert.equal(body.includes(fixture.accessToken), false);
  assert.equal(body.includes("sub_test-account"), false);
  assert.equal(body.includes("opaque-refresh-for-test"), false);

  const logout = await handle(new Request("https://storymemory-padiem.pages.dev/auth/logout", {
    method: "POST",
    headers: { origin: "https://storymemory-padiem.pages.dev", cookie: "storymemory_refresh=opaque-refresh-for-test" }
  }), fixture.env);
  assert.equal(logout.status, 204);
  assert.equal(await logout.text(), "");
  assert.ok(logout.headers.getSetCookie().some((value) => value.startsWith("__Host-storymemory-access=") && value.includes("Max-Age=0")));
  assert.ok(fixture.calls.some((call) => call.url === "https://auth.padiem.net/logout"));
  assert.equal(fixture.calls.some((call) => call.options.body?.toString().includes(fixture.accessToken)), false);
});

test("logout rejects a cross-origin request before making an auth request", async () => {
  const fixture = await configuredFixture();
  const handle = createStoryMemorySharedAuth({ fetcher: fixture.fetcher, now: () => now });
  const before = fixture.calls.length;
  const response = await handle(new Request("https://storymemory-padiem.pages.dev/auth/logout", {
    method: "POST",
    headers: { origin: "https://evil.example", cookie: "storymemory_refresh=opaque-refresh-for-test" }
  }), fixture.env);
  assert.equal(response.status, 403);
  assert.equal(fixture.calls.length, before);
});

test("expired service access cookie refreshes server-side and returns no tokens in status JSON", async () => {
  const fixture = await configuredFixture();
  const handle = createStoryMemorySharedAuth({ fetcher: fixture.fetcher, now: () => now });
  const response = await handle(new Request("https://storymemory-padiem.pages.dev/auth/status", {
    headers: { cookie: "__Host-storymemory-access=" + fixture.expiredAccessToken + "; storymemory_refresh=opaque-refresh-for-test" }
  }), fixture.env);
  assert.equal(response.status, 200);
  const body = await response.text();
  assert.deepEqual(JSON.parse(body), { configured: true, authenticated: true, syncEnabled: false });
  assert.equal(body.includes(fixture.accessToken), false);
  assert.ok(response.headers.getSetCookie().some((value) => value.startsWith("__Host-storymemory-access=")));
  assert.ok(fixture.calls.some((call) => call.url === "https://auth.padiem.net/token" && call.options.body?.toString().includes("grant_type=refresh_token")));
});

test("invalid callback only clears its one-time state cookie", async () => {
  const fixture = await configuredFixture();
  const handle = createStoryMemorySharedAuth({ fetcher: fixture.fetcher, now: () => now });
  const response = await handle(new Request("https://storymemory-padiem.pages.dev/auth/callback?code=" + "A".repeat(32) + "." + "B".repeat(32) + "&state=wrong", {
    headers: { cookie: "__Host-storymemory-auth-state=untrusted; __Host-storymemory-access=existing-access; storymemory_refresh=existing-refresh" }
  }), fixture.env);
  assert.equal(response.status, 302);
  assert.equal(response.headers.get("location"), "https://storymemory-padiem.pages.dev/?shared_login=failed");
  const cookies = response.headers.getSetCookie();
  assert.equal(cookies.length, 1);
  assert.ok(cookies[0].startsWith("__Host-storymemory-auth-state="));
  assert.equal(fixture.calls.length, 0);
});

test("unconfigured UI hides common login and keeps auth data out of local storage", async () => {
  const installs = [];
  const redirects = [];
  const bridge = {
    installStoryMemoryAuthBridge(value) { installs.push(value); },
    setStoryMemoryAuthSession(value) { installs.push({ session: value }); }
  };
  await initializeStoryMemorySharedAuth({
    fetcher: async () => Response.json({ configured: false, authenticated: false, syncEnabled: false }),
    location: { assign: (value) => redirects.push(value) },
    bridge
  });
  assert.equal(installs[0].configured, false);
  assert.equal(installs[0].syncEnabled, false);
  await assert.rejects(installs[0].openSignIn(), /AUTH_NOT_CONFIGURED/);
  assert.deepEqual(redirects, []);

  const uiSource = await readFile(new URL("../public/storymemory-shared-auth-ui.mjs", import.meta.url), "utf8");
  const authSource = await readFile(new URL("../public/storymemory-shared-auth.mjs", import.meta.url), "utf8");
  const worker = await readFile(new URL("../public/_worker.js", import.meta.url), "utf8");
  const index = await readFile(new URL("../public/index.html", import.meta.url), "utf8");
  const readback = await readFile(new URL("../public/readback_index.html/index.html", import.meta.url), "utf8");
  for (const html of [index, readback]) {
    assert.match(html, /id="authGatePrimary" hidden/);
    assert.match(html, /기기 간 동기화는 아직 연결되지 않았습니다/);
    assert.match(html, /REMOTE_SYNC_NOT_ENABLED/);
    assert.doesNotMatch(html, /localStorage\.setItem\(STORYMEMORY_AUTH_STATE_KEY/);
  }
  assert.doesNotMatch(uiSource, /localStorage|console\.(?:log|info|warn|error)/);
  assert.doesNotMatch(authSource, /localStorage|console\.(?:log|info|warn|error)/);
  assert.match(worker, /createStoryMemorySharedAuth/);
  assert.match(worker, /handleStoryMemorySharedAuth\(request, env\)/);
});

test("configured UI redirects to common login and logs out through same-origin POST without sync", async () => {
  const installs = [];
  const redirects = [];
  const calls = [];
  const bridge = {
    installStoryMemoryAuthBridge(value) { installs.push(value); },
    setStoryMemoryAuthSession(value) { calls.push({ session: value }); }
  };
  await initializeStoryMemorySharedAuth({
    fetcher: async (url, options = {}) => {
      calls.push({ url, options });
      return Response.json({ configured: true, authenticated: true, syncEnabled: false });
    },
    location: { assign: (value) => redirects.push(value) },
    bridge
  });
  assert.equal(installs[0].configured, true);
  assert.equal(installs[0].authenticated, true);
  assert.equal(installs[0].syncEnabled, false);
  await installs[0].openSignIn();
  assert.deepEqual(redirects, ["/auth/login?next=%2F"]);

  const logoutUi = initializeStoryMemorySharedAuth;
  const authenticatedBridge = {
    installStoryMemoryAuthBridge(value) { installs.push(value); },
    setStoryMemoryAuthSession(value) { calls.push({ session: value }); }
  };
  await logoutUi({
    fetcher: async (url, options = {}) => {
      calls.push({ url, options });
      if (url === "/auth/status") return Response.json({ configured: true, authenticated: true, syncEnabled: false });
      return new Response(null, { status: 204 });
    },
    location: { assign: (value) => redirects.push(value) },
    bridge: authenticatedBridge
  });
  await installs[1].signOut();
  assert.ok(calls.some((call) => call.url === "/auth/logout" && call.options.method === "POST" && call.options.credentials === "same-origin"));
  assert.deepEqual(calls.at(-1), { session: { authenticated: false } });
  assert.equal(installs[1].syncEnabled, false);
});
