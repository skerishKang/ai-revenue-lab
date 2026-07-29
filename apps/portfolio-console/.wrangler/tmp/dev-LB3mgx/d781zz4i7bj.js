var __defProp = Object.defineProperty;
var __name = (target, value) => __defProp(target, "name", { value, configurable: true });

// .wrangler/tmp/pages-Y1G9U5/functionsWorker-0.860256038654071.mjs
var __create = Object.create;
var __defProp2 = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __getProtoOf = Object.getPrototypeOf;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __name2 = /* @__PURE__ */ __name((target, value) => __defProp2(target, "name", { value, configurable: true }), "__name");
var __esm = /* @__PURE__ */ __name((fn, res, err) => /* @__PURE__ */ __name(function __init() {
  if (err) throw err[0];
  try {
    return fn && (res = (0, fn[__getOwnPropNames(fn)[0]])(fn = 0)), res;
  } catch (e) {
    throw err = [e], e;
  }
}, "__init"), "__esm");
var __commonJS = /* @__PURE__ */ __name((cb, mod) => /* @__PURE__ */ __name(function __require() {
  try {
    return mod || (0, cb[__getOwnPropNames(cb)[0]])((mod = { exports: {} }).exports, mod), mod.exports;
  } catch (e) {
    throw mod = 0, e;
  }
}, "__require"), "__commonJS");
var __copyProps = /* @__PURE__ */ __name((to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp2(to, key, { get: /* @__PURE__ */ __name(() => from[key], "get"), enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
}, "__copyProps");
var __toESM = /* @__PURE__ */ __name((mod, isNodeMode, target) => (target = mod != null ? __create(__getProtoOf(mod)) : {}, __copyProps(
  // If the importer is in node compatibility mode or this is not an ESM
  // file that has been converted to a CommonJS file using a Babel-
  // compatible transform (i.e. "__esModule" has not been set), then set
  // "default" to the CommonJS "module.exports" for node compatibility.
  isNodeMode || !mod || !mod.__esModule ? __defProp2(target, "default", { value: mod, enumerable: true }) : target,
  mod
)), "__toESM");
function base64Url(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/=/g, "").replace(/\+/g, "-").replace(/\//g, "_");
}
__name(base64Url, "base64Url");
function encodeJson(value) {
  return base64Url(new TextEncoder().encode(JSON.stringify(value)));
}
__name(encodeJson, "encodeJson");
function decodePkcs8(privateKeyPkcs8) {
  const normalized = String(privateKeyPkcs8 || "").replace(/-----BEGIN PRIVATE KEY-----/g, "").replace(/-----END PRIVATE KEY-----/g, "").replace(/\s+/g, "");
  if (!normalized) throw new GitHubAuthError("PRIVATE_KEY_INVALID", "GitHub App authentication failed.");
  try {
    const binary = atob(normalized);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    throw new GitHubAuthError("PRIVATE_KEY_INVALID", "GitHub App authentication failed.");
  }
}
__name(decodePkcs8, "decodePkcs8");
async function createGitHubAppJwt({ appId, privateKeyPkcs8, nowSeconds, cryptoImpl = globalThis.crypto }) {
  if (!cryptoImpl?.subtle) throw new GitHubAuthError("CRYPTO_UNAVAILABLE", "GitHub App authentication failed.");
  const now = Number.isFinite(nowSeconds) ? Math.floor(nowSeconds) : Math.floor(Date.now() / 1e3);
  const header = { alg: "RS256", typ: "JWT" };
  const payload = { iat: now - 60, exp: now + 540, iss: String(appId) };
  const unsigned = `${encodeJson(header)}.${encodeJson(payload)}`;
  try {
    const key = await cryptoImpl.subtle.importKey(
      "pkcs8",
      decodePkcs8(privateKeyPkcs8),
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["sign"]
    );
    const signature = await cryptoImpl.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(unsigned));
    return `${unsigned}.${base64Url(new Uint8Array(signature))}`;
  } catch (error) {
    if (error instanceof GitHubAuthError) throw error;
    throw new GitHubAuthError("JWT_SIGNING_FAILED", "GitHub App authentication failed.");
  }
}
__name(createGitHubAppJwt, "createGitHubAppJwt");
var API_VERSION;
var ACCEPT;
var USER_AGENT;
var GitHubAuthError;
var InstallationTokenProvider;
var init_github_app_auth = __esm({
  "_lib/github-app-auth.js"() {
    init_functionsRoutes_0_25189528211003487();
    API_VERSION = "2026-03-10";
    ACCEPT = "application/vnd.github+json";
    USER_AGENT = "ai-revenue-portfolio-console";
    GitHubAuthError = class extends Error {
      static {
        __name(this, "GitHubAuthError");
      }
      static {
        __name2(this, "GitHubAuthError");
      }
      constructor(code, message) {
        super(message);
        this.name = "GitHubAuthError";
        this.code = code;
      }
    };
    __name2(base64Url, "base64Url");
    __name2(encodeJson, "encodeJson");
    __name2(decodePkcs8, "decodePkcs8");
    __name2(createGitHubAppJwt, "createGitHubAppJwt");
    InstallationTokenProvider = class {
      static {
        __name(this, "InstallationTokenProvider");
      }
      static {
        __name2(this, "InstallationTokenProvider");
      }
      constructor({ appId, installationId, privateKeyPkcs8, fetchImpl = fetch, now = /* @__PURE__ */ __name2(() => Date.now(), "now"), cryptoImpl = globalThis.crypto }) {
        this.appId = appId;
        this.installationId = installationId;
        this.privateKeyPkcs8 = privateKeyPkcs8;
        this.fetchImpl = fetchImpl;
        this.now = now;
        this.cryptoImpl = cryptoImpl;
        this.cached = null;
        this.inFlight = null;
      }
      invalidate() {
        this.cached = null;
      }
      async exchange() {
        const nowMs = this.now();
        const jwt = await createGitHubAppJwt({
          appId: this.appId,
          privateKeyPkcs8: this.privateKeyPkcs8,
          nowSeconds: Math.floor(nowMs / 1e3),
          cryptoImpl: this.cryptoImpl
        });
        const response = await this.fetchImpl(
          `https://api.github.com/app/installations/${encodeURIComponent(String(this.installationId))}/access_tokens`,
          { method: "POST", headers: {
            Accept: ACCEPT,
            Authorization: `Bearer ${jwt}`,
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": USER_AGENT
          } }
        );
        if (!response.ok) throw new GitHubAuthError("INSTALLATION_TOKEN_EXCHANGE_FAILED", "GitHub App authentication failed.");
        let data;
        try {
          data = await response.json();
        } catch {
          throw new GitHubAuthError("INSTALLATION_TOKEN_RESPONSE_INVALID", "GitHub App authentication failed.");
        }
        const expiresAtMs = Date.parse(data?.expires_at || "");
        if (typeof data?.token !== "string" || !data.token || !Number.isFinite(expiresAtMs)) {
          throw new GitHubAuthError("INSTALLATION_TOKEN_RESPONSE_INVALID", "GitHub App authentication failed.");
        }
        this.cached = { token: data.token, expiresAtMs };
        return data.token;
      }
      getToken({ forceRefresh = false } = {}) {
        const nowMs = this.now();
        if (!forceRefresh && this.cached && this.cached.expiresAtMs - 6e4 > nowMs) return Promise.resolve(this.cached.token);
        if (forceRefresh) this.cached = null;
        if (this.inFlight) return this.inFlight;
        let wrapped;
        wrapped = this.exchange().finally(() => {
          if (this.inFlight === wrapped) this.inFlight = null;
        });
        this.inFlight = wrapped;
        return wrapped;
      }
    };
  }
});
function assertAllowedRepository(repository) {
  if (!ALLOWED_REPOSITORIES.includes(repository)) {
    const error = new Error("Repository is not allowlisted.");
    error.code = "REPOSITORY_NOT_ALLOWED";
    throw error;
  }
  return repository;
}
__name(assertAllowedRepository, "assertAllowedRepository");
var GITHUB_REPOSITORY;
var ALLOWED_REPOSITORIES;
var BUSINESS_GITHUB_MAP;
var init_business_github_map = __esm({
  "_lib/business-github-map.js"() {
    init_functionsRoutes_0_25189528211003487();
    GITHUB_REPOSITORY = "skerishKang/ai-revenue-lab";
    ALLOWED_REPOSITORIES = Object.freeze([GITHUB_REPOSITORY]);
    BUSINESS_GITHUB_MAP = Object.freeze([
      // ── 1–4: CANONICAL  ──
      { number: 1, repository: GITHUB_REPOSITORY, issueNumber: 108, uiPhaseIssue: 108, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 111 },
      { number: 2, repository: GITHUB_REPOSITORY, issueNumber: 43, uiPhaseIssue: 107, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 88 },
      { number: 3, repository: GITHUB_REPOSITORY, issueNumber: 55, uiPhaseIssue: 75, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 85 },
      { number: 4, repository: GITHUB_REPOSITORY, issueNumber: 37, uiPhaseIssue: 37, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 94 },
      // ── 5–6  ──
      { number: 5, repository: GITHUB_REPOSITORY, issueNumber: 99, uiPhaseIssue: 99, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 109 },
      { number: 6, repository: GITHUB_REPOSITORY, issueNumber: 98, uiPhaseIssue: 155, uxPhaseIssue: 165, bePhaseIssue: null, fallbackPrNumber: null },
      // ── 7–12  ──
      { number: 7, repository: GITHUB_REPOSITORY, issueNumber: 166, uiPhaseIssue: 166, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 174 },
      { number: 8, repository: GITHUB_REPOSITORY, issueNumber: 168, uiPhaseIssue: 168, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 176 },
      { number: 9, repository: GITHUB_REPOSITORY, issueNumber: 170, uiPhaseIssue: 170, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 175 },
      { number: 10, repository: GITHUB_REPOSITORY, issueNumber: 171, uiPhaseIssue: 171, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 177 },
      { number: 11, repository: GITHUB_REPOSITORY, issueNumber: 172, uiPhaseIssue: 172, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 179 },
      { number: 12, repository: GITHUB_REPOSITORY, issueNumber: 173, uiPhaseIssue: 173, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 178 },
      // ── 13–14: CANONICAL  ──
      { number: 13, repository: GITHUB_REPOSITORY, issueNumber: 76, uiPhaseIssue: 76, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 78 },
      { number: 14, repository: GITHUB_REPOSITORY, issueNumber: 80, uiPhaseIssue: 138, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: 142 },
      // ── 15–22  ──
      { number: 15, repository: GITHUB_REPOSITORY, issueNumber: 187, uiPhaseIssue: 188, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 16, repository: GITHUB_REPOSITORY, issueNumber: 189, uiPhaseIssue: 190, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 17, repository: GITHUB_REPOSITORY, issueNumber: 191, uiPhaseIssue: 192, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 18, repository: GITHUB_REPOSITORY, issueNumber: 196, uiPhaseIssue: 197, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 19, repository: GITHUB_REPOSITORY, issueNumber: 198, uiPhaseIssue: 199, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 20, repository: GITHUB_REPOSITORY, issueNumber: 200, uiPhaseIssue: 201, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 21, repository: GITHUB_REPOSITORY, issueNumber: 204, uiPhaseIssue: 205, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 22, repository: GITHUB_REPOSITORY, issueNumber: 222, uiPhaseIssue: 223, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      // ── 23–25: existing-project (separate repos)  ──
      { number: 23, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 24, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 25, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      // ── 26–35  ──
      { number: 26, repository: GITHUB_REPOSITORY, issueNumber: 226, uiPhaseIssue: 227, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 27, repository: GITHUB_REPOSITORY, issueNumber: 230, uiPhaseIssue: 231, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 28, repository: GITHUB_REPOSITORY, issueNumber: 234, uiPhaseIssue: 235, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 29, repository: GITHUB_REPOSITORY, issueNumber: 236, uiPhaseIssue: 237, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 30, repository: GITHUB_REPOSITORY, issueNumber: 240, uiPhaseIssue: 242, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 31, repository: GITHUB_REPOSITORY, issueNumber: 241, uiPhaseIssue: 243, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 32, repository: GITHUB_REPOSITORY, issueNumber: 246, uiPhaseIssue: 248, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 33, repository: GITHUB_REPOSITORY, issueNumber: 247, uiPhaseIssue: 249, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 34, repository: GITHUB_REPOSITORY, issueNumber: 252, uiPhaseIssue: 254, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 35, repository: GITHUB_REPOSITORY, issueNumber: 253, uiPhaseIssue: 255, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      // ── 36–43: product-decision + Phase 1 UI issues  ──
      { number: 36, repository: GITHUB_REPOSITORY, issueNumber: 266, uiPhaseIssue: 268, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 37, repository: GITHUB_REPOSITORY, issueNumber: 259, uiPhaseIssue: 260, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 38, repository: GITHUB_REPOSITORY, issueNumber: 267, uiPhaseIssue: 269, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 39, repository: GITHUB_REPOSITORY, issueNumber: 261, uiPhaseIssue: 262, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 40, repository: GITHUB_REPOSITORY, issueNumber: 270, uiPhaseIssue: 272, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 41, repository: GITHUB_REPOSITORY, issueNumber: 271, uiPhaseIssue: 273, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 42, repository: GITHUB_REPOSITORY, issueNumber: 274, uiPhaseIssue: 276, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 43, repository: GITHUB_REPOSITORY, issueNumber: 275, uiPhaseIssue: 277, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      // ── 44: portfolio-console (existing-project)  ──
      { number: 44, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      // ── 45–55: candidate backlog (no mapped issues yet)  ──
      { number: 45, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 46, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 47, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 48, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 49, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 50, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 51, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 52, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 53, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 54, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null },
      { number: 55, repository: null, issueNumber: null, uiPhaseIssue: null, uxPhaseIssue: null, bePhaseIssue: null, fallbackPrNumber: null }
    ]);
    __name2(assertAllowedRepository, "assertAllowedRepository");
  }
});
function esc(val) {
  return JSON.stringify(val);
}
__name(esc, "esc");
function buildStatusQuery(opts = {}) {
  const { prSearchLimit = 10 } = opts;
  const mappedEntries = BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY);
  const allIssueNumbers = /* @__PURE__ */ new Set();
  for (const m of mappedEntries) {
    if (m.issueNumber) allIssueNumbers.add(m.issueNumber);
    if (m.uiPhaseIssue) allIssueNumbers.add(m.uiPhaseIssue);
    if (m.uxPhaseIssue) allIssueNumbers.add(m.uxPhaseIssue);
    if (m.bePhaseIssue) allIssueNumbers.add(m.bePhaseIssue);
  }
  const issueSelections = [...allIssueNumbers].sort((a, b) => a - b).map((n) => `  issue${n}: issue(number: ${n}) {
    number title state stateReason updatedAt url body
  }`).join("\n");
  const phaseIssueNumbers = /* @__PURE__ */ new Set();
  for (const m of mappedEntries) {
    if (m.uiPhaseIssue) phaseIssueNumbers.add(m.uiPhaseIssue);
    if (m.uxPhaseIssue) phaseIssueNumbers.add(m.uxPhaseIssue);
    if (m.bePhaseIssue) phaseIssueNumbers.add(m.bePhaseIssue);
  }
  const PR_FIELDS = `number title state isDraft merged headRefOid headRefName baseRefOid baseRefName updatedAt url body
        commits(last: 1) { nodes { commit { statusCheckRollup {
          state contexts(first: 100) { totalCount nodes {
            __typename
            ... on CheckRun { status conclusion name }
            ... on StatusContext { state context }
          } }
        } } } }`;
  const searchSelection = /* @__PURE__ */ __name2((alias, expression, indent) => `  ${alias}: search(
    query: ${esc(`${SEARCH_PR_QUERY_PREFIX} ${expression}`)}
    type: ISSUE
    first: ${prSearchLimit}
  ) {
    issueCount
    nodes {
      ... on PullRequest {
        ${PR_FIELDS}
      }
    }
  }`, "searchSelection");
  const prSearchSelections = [...phaseIssueNumbers].sort((a, b) => a - b).map((n) => [
    searchSelection(`prSearchRefs${n}`, `"Refs #${n}"`),
    searchSelection(`prSearchRelated${n}`, `"Related to #${n}"`)
  ].join("\n")).join("\n");
  const fallbackPrSelections = mappedEntries.filter((m) => m.fallbackPrNumber).map((m) => `  fallbackPr${m.fallbackPrNumber}: pullRequest(number: ${m.fallbackPrNumber}) {
    ${PR_FIELDS}
  }`).join("\n");
  const draftQuery = `repo:${GITHUB_REPOSITORY} is:pr is:open is:draft`;
  return `query PortfolioAutoSync($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    nameWithOwner url
    defaultBranchRef { name target { ... on Commit { oid messageHeadline committedDate } } }
    issues(first: 1, states: OPEN) { totalCount }
    pullRequests(first: 1, states: OPEN) { totalCount }
${issueSelections}
${fallbackPrSelections}
  }
  draftPullRequests: search(query: ${esc(draftQuery)}, type: ISSUE, first: 1) { issueCount }
${prSearchSelections}
}`;
}
__name(buildStatusQuery, "buildStatusQuery");
function getPrSearchAliases(issueNum) {
  return [`prSearchRefs${issueNum}`, `prSearchRelated${issueNum}`];
}
__name(getPrSearchAliases, "getPrSearchAliases");
function getRequestBudget() {
  return { cold: 2, cachedToken: 1, worstCase: 4 };
}
__name(getRequestBudget, "getRequestBudget");
var SEARCH_PR_QUERY_PREFIX;
var init_business_github_query = __esm({
  "_lib/business-github-query.js"() {
    init_functionsRoutes_0_25189528211003487();
    init_business_github_map();
    SEARCH_PR_QUERY_PREFIX = `repo:${GITHUB_REPOSITORY} type:pr`;
    __name2(esc, "esc");
    __name2(buildStatusQuery, "buildStatusQuery");
    __name2(getPrSearchAliases, "getPrSearchAliases");
    __name2(getRequestBudget, "getRequestBudget");
  }
});
function parseVerdictBlocks(text, expectedBusinessNumber, expectedPhase) {
  if (!text) return [];
  const regex = /<!--\s*portfolio-verdict\s*([\s\S]*?)-->/g;
  const results = [];
  let match2;
  while ((match2 = regex.exec(text)) !== null) {
    const block = match2[1];
    const businessNum = parseInt(block.match(/business:\s*(\d+)/)?.[1], 10);
    const phase = block.match(/phase:\s*(ui|ux|backend)/)?.[1];
    const verdict = block.match(/verdict:\s*(\S+)/)?.[1]?.trim() || null;
    const acceptedHead = block.match(/accepted_head:\s*(\S+)/)?.[1]?.trim() || null;
    if (businessNum !== expectedBusinessNumber || phase !== expectedPhase) continue;
    if (!businessNum || !phase || !verdict) {
      results.push({ status: "invalid", verdict: null, acceptedHead: null, businessNumber: businessNum, phase, source: null, reason: "INCOMPLETE_BLOCK" });
      continue;
    }
    const validForPhase = VALID_VERDICTS[phase];
    if (!validForPhase || !validForPhase.includes(verdict)) {
      results.push({ status: "invalid", verdict, acceptedHead, businessNumber: businessNum, phase, source: null, reason: `INVALID_VERDICT_PHASE: phase=${phase} verdict=${verdict}` });
      continue;
    }
    if (VERDICTS_REQUIRING_HEAD.has(verdict)) {
      if (!acceptedHead || !SHA_HEX.test(acceptedHead)) {
        results.push({ status: "invalid", verdict, acceptedHead, businessNumber: businessNum, phase, source: null, reason: "MISSING_OR_INVALID_ACCEPTED_HEAD" });
        continue;
      }
    }
    results.push({ status: "verified", verdict, acceptedHead, businessNumber: businessNum, phase, source: null, reason: null });
  }
  return results;
}
__name(parseVerdictBlocks, "parseVerdictBlocks");
function resolvePhaseVerdictFromPool({
  expectedBusinessNumber,
  expectedPhase,
  issueBody,
  prBody,
  staticFallback
}) {
  const allBlocks = [];
  if (issueBody) {
    allBlocks.push(...parseVerdictBlocks(issueBody, expectedBusinessNumber, expectedPhase).map((b) => ({ ...b, source: "issue_body" })));
  }
  if (prBody) {
    allBlocks.push(...parseVerdictBlocks(prBody, expectedBusinessNumber, expectedPhase).map((b) => ({ ...b, source: "pr_body" })));
  }
  const verified = allBlocks.filter((b) => b.status === "verified");
  const invalid = allBlocks.filter((b) => b.status === "invalid");
  const uniqueVerdicts = new Set(verified.map((b) => b.verdict));
  if (uniqueVerdicts.size > 1) {
    return { status: "conflict", verdict: null, acceptedHead: null, businessNumber: expectedBusinessNumber, phase: expectedPhase, source: null, reason: "MULTIPLE_CONFLICTING_VERDICTS" };
  }
  if (verified.length >= 2) {
    const heads = new Set(verified.map((b) => b.acceptedHead));
    if (heads.size > 1) {
      return { status: "conflict", verdict: verified[0].verdict, acceptedHead: null, businessNumber: expectedBusinessNumber, phase: expectedPhase, source: null, reason: "CONFLICTING_ACCEPTED_HEADS" };
    }
  }
  if (verified.length === 1) {
    return verified[0];
  }
  if (staticFallback) {
    return { status: "unverified", verdict: staticFallback, acceptedHead: null, businessNumber: expectedBusinessNumber, phase: expectedPhase, source: "static_fallback", reason: "STATIC_FALLBACK_NOT_MACHINE_VERIFIED" };
  }
  if (invalid.length > 0) {
    return { ...invalid[0], businessNumber: expectedBusinessNumber, phase: expectedPhase, source: invalid[0].source || null };
  }
  return { status: "unverified", verdict: null, acceptedHead: null, businessNumber: expectedBusinessNumber, phase: expectedPhase, source: null, reason: "NO_VERDICT_FOUND" };
}
__name(resolvePhaseVerdictFromPool, "resolvePhaseVerdictFromPool");
var VALID_VERDICTS;
var VERDICTS_REQUIRING_HEAD;
var SHA_HEX;
var init_business_verdict_parser = __esm({
  "_lib/business-verdict-parser.js"() {
    init_functionsRoutes_0_25189528211003487();
    init_business_github_map();
    VALID_VERDICTS = {
      ui: ["UI_NOT_READY", "UI_CONDITIONALLY_READY", "UI_APPROVED"],
      ux: ["UX_NOT_READY", "UX_CONDITIONALLY_READY", "UX_APPROVED"],
      backend: ["BACKEND_FROZEN", "BACKEND_DEFERRED", "BACKEND_AUTHORIZED", "BACKEND_IN_PROGRESS", "BACKEND_IMPLEMENTED"]
    };
    VERDICTS_REQUIRING_HEAD = /* @__PURE__ */ new Set(["UI_APPROVED", "UX_APPROVED", "BACKEND_AUTHORIZED", "BACKEND_IMPLEMENTED"]);
    SHA_HEX = /^[0-9a-f]{40}$/;
    __name2(parseVerdictBlocks, "parseVerdictBlocks");
    __name2(resolvePhaseVerdictFromPool, "resolvePhaseVerdictFromPool");
  }
});
function parseStructuredMarker(body) {
  if (!body) return null;
  const bizMatch = body.match(/business:\s*(\d+)/);
  const phaseMatch = body.match(/phase:\s*(ui|ux|backend)/);
  if (bizMatch && phaseMatch) return { businessNumber: parseInt(bizMatch[1], 10), phase: phaseMatch[1] };
  return null;
}
__name(parseStructuredMarker, "parseStructuredMarker");
function parseRefs(body) {
  if (!body) return [];
  const refs = [];
  const regex = /Refs\s+#(\d+)/gi;
  let match2;
  while ((match2 = regex.exec(body)) !== null) refs.push(parseInt(match2[1], 10));
  return refs;
}
__name(parseRefs, "parseRefs");
function parseRelatedTo(body) {
  if (!body) return [];
  const refs = [];
  const regex = /Related\s+to\s+#(\d+)/gi;
  let match2;
  while ((match2 = regex.exec(body)) !== null) refs.push(parseInt(match2[1], 10));
  return refs;
}
__name(parseRelatedTo, "parseRelatedTo");
function normalizeChecks(rawPr) {
  const rollup = rawPr?.commits?.nodes?.[0]?.commit?.statusCheckRollup || null;
  if (!rollup) return { state: "unavailable", source: "pr_head_rollup", total: 0, completed: 0 };
  const contexts = Array.isArray(rollup?.contexts?.nodes) ? rollup.contexts.nodes : [];
  const total = Number(rollup?.contexts?.totalCount) || contexts.length;
  const aggregateState = String(rollup.state || "").toUpperCase();
  const normalizedState = aggregateState === "SUCCESS" ? "pass" : aggregateState === "FAILURE" || aggregateState === "ERROR" ? "fail" : aggregateState === "PENDING" || aggregateState === "EXPECTED" ? "pending" : "unavailable";
  let completed = 0;
  for (const ctx of contexts) {
    const tn = String(ctx?.__typename || "");
    if (tn === "CheckRun" && String(ctx?.status || "").toUpperCase() === "COMPLETED") completed++;
    else if (tn === "StatusContext" && CHECK_TERMINAL_STATES.has(String(ctx?.state || "").toUpperCase())) completed++;
  }
  const result = { state: normalizedState, source: "pr_head_rollup", total, completed };
  if (total > contexts.length) result.truncated = true;
  return result;
}
__name(normalizeChecks, "normalizeChecks");
function normalizeRawPr(node) {
  if (!node || !node.number) return null;
  return {
    number: Number(node.number),
    title: String(node.title || ""),
    state: String(node.state || "").toLowerCase(),
    draft: Boolean(node.isDraft),
    merged: Boolean(node.merged),
    headSha: String(node.headRefOid || ""),
    headRef: String(node.headRefName || ""),
    baseSha: String(node.baseRefOid || ""),
    baseRef: String(node.baseRefName || ""),
    updatedAt: String(node.updatedAt || ""),
    url: String(node.url || ""),
    body: String(node.body || ""),
    checks: normalizeChecks(node)
  };
}
__name(normalizeRawPr, "normalizeRawPr");
function conventionMatches(pr, businessNumber, phase, phaseIssueNumber) {
  const bizRegex = new RegExp(`business-${businessNumber}(?!\\d)`, "i");
  const phaseRegex = new RegExp(`${phase}-${phaseIssueNumber}(?!\\d)`, "i");
  return bizRegex.test(pr.title || "") || bizRegex.test(pr.headRef || "") || phaseRegex.test(pr.title || "") || phaseRegex.test(pr.headRef || "");
}
__name(conventionMatches, "conventionMatches");
function discovered(pr, method, truncated) {
  const result = { status: "discovered", pullRequest: { ...pr, discoveryMethod: method }, candidates: null, reason: null };
  if (truncated) result.truncated = true;
  return result;
}
__name(discovered, "discovered");
function discoverPr({
  businessNumber,
  phaseIssueNumber,
  phase,
  searchResults,
  fallbackPrNode
}) {
  if (!phaseIssueNumber) {
    return { status: "unavailable", pullRequest: null, candidates: null, reason: "NO_PHASE_ISSUE" };
  }
  const pool = Array.isArray(searchResults) ? { nodes: searchResults, truncated: false } : searchResults || { nodes: [], truncated: false };
  const truncated = Boolean(pool.truncated);
  const candidates = (pool.nodes || []).map(normalizeRawPr).filter(Boolean);
  const conflict = /* @__PURE__ */ __name2((reason, matches) => ({ status: "conflict", pullRequest: null, candidates: matches.map((p) => p.number), reason }), "conflict");
  const markerMatches = candidates.filter((pr) => {
    const marker = parseStructuredMarker(pr.body);
    return marker && marker.businessNumber === businessNumber && marker.phase === phase;
  });
  if (markerMatches.length === 1) return discovered(markerMatches[0], "marker", truncated);
  if (markerMatches.length > 1) return conflict("MULTIPLE_MARKER_MATCHES", markerMatches);
  const refsMatches = candidates.filter((pr) => parseRefs(pr.body).includes(phaseIssueNumber));
  if (refsMatches.length === 1) return discovered(refsMatches[0], "refs", truncated);
  if (refsMatches.length > 1) return conflict("MULTIPLE_REFS_MATCHES", refsMatches);
  const relatedMatches = candidates.filter((pr) => parseRelatedTo(pr.body).includes(phaseIssueNumber));
  if (relatedMatches.length === 1) return discovered(relatedMatches[0], "related_to", truncated);
  if (relatedMatches.length > 1) return conflict("MULTIPLE_RELATED_MATCHES", relatedMatches);
  const branchMatches = candidates.filter((pr) => conventionMatches(pr, businessNumber, phase, phaseIssueNumber));
  if (branchMatches.length === 1) return discovered(branchMatches[0], "branch", truncated);
  if (branchMatches.length > 1) return conflict("MULTIPLE_BRANCH_MATCHES", branchMatches);
  const fallbackPr = normalizeRawPr(fallbackPrNode);
  if (fallbackPr) return discovered(fallbackPr, "fallback", false);
  const unavailable = { status: "unavailable", pullRequest: null, candidates: null, reason: "NO_DISCOVERY_MATCH" };
  if (truncated) unavailable.truncated = true;
  return unavailable;
}
__name(discoverPr, "discoverPr");
function reconcileWithFallback(discoveryResult, fallbackPrNode) {
  if (!fallbackPrNode?.number) return discoveryResult;
  if (discoveryResult.status !== "discovered") return discoveryResult;
  if (discoveryResult.pullRequest.discoveryMethod === "fallback") return discoveryResult;
  const fallbackNumber = Number(fallbackPrNode.number);
  if (fallbackNumber === discoveryResult.pullRequest.number) return discoveryResult;
  return {
    status: "conflict",
    pullRequest: null,
    candidates: [discoveryResult.pullRequest.number, fallbackNumber],
    reason: "FALLBACK_DISCOVERY_MISMATCH"
  };
}
__name(reconcileWithFallback, "reconcileWithFallback");
function discoverBusinessPrs({ mapping, phaseIssueResults, fallbackPrNode }) {
  const result = { ui: null, ux: null, backend: null };
  const phases = [
    { key: "ui", issueKey: "uiPhaseIssue", phase: "ui" },
    { key: "ux", issueKey: "uxPhaseIssue", phase: "ux" },
    { key: "backend", issueKey: "bePhaseIssue", phase: "backend" }
  ];
  for (const { key, issueKey, phase } of phases) {
    const issueNum = mapping[issueKey];
    const searchPool = issueNum ? phaseIssueResults?.[`prSearch${issueNum}`] || { nodes: [], truncated: false } : { nodes: [], truncated: false };
    const discovery = discoverPr({
      businessNumber: mapping.number,
      phaseIssueNumber: issueNum || null,
      phase,
      searchResults: searchPool,
      fallbackPrNode: mapping.fallbackPrNumber ? fallbackPrNode : null
    });
    result[key] = reconcileWithFallback(discovery, mapping.fallbackPrNumber ? fallbackPrNode : null);
  }
  return result;
}
__name(discoverBusinessPrs, "discoverBusinessPrs");
var CHECK_TERMINAL_STATES;
var init_business_pr_discovery = __esm({
  "_lib/business-pr-discovery.js"() {
    init_functionsRoutes_0_25189528211003487();
    __name2(parseStructuredMarker, "parseStructuredMarker");
    __name2(parseRefs, "parseRefs");
    __name2(parseRelatedTo, "parseRelatedTo");
    CHECK_TERMINAL_STATES = /* @__PURE__ */ new Set(["SUCCESS", "FAILURE", "ERROR"]);
    __name2(normalizeChecks, "normalizeChecks");
    __name2(normalizeRawPr, "normalizeRawPr");
    __name2(conventionMatches, "conventionMatches");
    __name2(discovered, "discovered");
    __name2(discoverPr, "discoverPr");
    __name2(reconcileWithFallback, "reconcileWithFallback");
    __name2(discoverBusinessPrs, "discoverBusinessPrs");
  }
});
function normalizeIssue(issue) {
  if (!issue) return null;
  return {
    number: Number(issue.number),
    title: String(issue.title || ""),
    state: String(issue.state || "").toLowerCase(),
    stateReason: issue.stateReason || null,
    updatedAt: issue.updatedAt || null,
    url: String(issue.url || "")
  };
}
__name(normalizeIssue, "normalizeIssue");
function discoverySummary(discovery) {
  if (!discovery) return null;
  const summary = {
    status: discovery.status,
    method: discovery.pullRequest?.discoveryMethod || null,
    candidates: discovery.candidates || null,
    reason: discovery.reason || null
  };
  if (discovery.truncated) summary.truncated = true;
  return summary;
}
__name(discoverySummary, "discoverySummary");
function mergeBusinessFacts({
  mapping,
  repositoryData,
  phaseIssueResults,
  fallbackPrNode,
  identitySource
  // Map<number, {uiStatus, uxStatus, backendStatus}>
}) {
  if (!mapping.repository) {
    return {
      number: mapping.number,
      connectionState: "unmapped",
      repository: null,
      productDecisionIssue: null,
      phaseIssues: null,
      currentPullRequests: null,
      phaseDiscovery: null,
      phaseVerdicts: null,
      activityAt: null,
      error: null
    };
  }
  const issueAlias = mapping.issueNumber ? `issue${mapping.issueNumber}` : null;
  const productDecisionIssue = normalizeIssue(issueAlias ? repositoryData?.[issueAlias] : null);
  const rawPhaseIssues = { ui: null, ux: null, backend: null };
  const phaseIssues = { ui: null, ux: null, backend: null };
  for (const phase of PHASES) {
    const issueNum = mapping[PHASE_ISSUE_KEYS[phase]];
    if (!issueNum) continue;
    rawPhaseIssues[phase] = repositoryData?.[`issue${issueNum}`] || null;
    phaseIssues[phase] = normalizeIssue(rawPhaseIssues[phase]);
  }
  const prDiscovery = discoverBusinessPrs({ mapping, phaseIssueResults, fallbackPrNode });
  const currentPullRequests = {
    ui: prDiscovery.ui?.pullRequest || null,
    ux: prDiscovery.ux?.pullRequest || null,
    backend: prDiscovery.backend?.pullRequest || null
  };
  const staticBiz = (identitySource || {})[mapping.number] || {};
  const phaseVerdicts = {};
  for (const phase of PHASES) {
    phaseVerdicts[phase] = resolvePhaseVerdictFromPool({
      expectedBusinessNumber: mapping.number,
      expectedPhase: phase,
      issueBody: rawPhaseIssues[phase]?.body || null,
      prBody: currentPullRequests[phase]?.body || null,
      staticFallback: staticBiz[STATIC_FALLBACK_KEYS[phase]] || null
    });
  }
  const diagnostics = [];
  for (const phase of PHASES) {
    if (prDiscovery[phase]?.status === "conflict") diagnostics.push("PR_DISCOVERY_CONFLICT");
  }
  if (!productDecisionIssue && mapping.issueNumber) diagnostics.push("ISSUE_UNAVAILABLE");
  const connectionState = diagnostics.length === 0 ? "connected" : "partial";
  const activityAt = (() => {
    const timestamps = [];
    if (productDecisionIssue?.updatedAt) timestamps.push(new Date(productDecisionIssue.updatedAt).getTime());
    for (const phase of PHASES) {
      const updatedAt = currentPullRequests[phase]?.updatedAt;
      if (updatedAt) timestamps.push(new Date(updatedAt).getTime());
    }
    const valid = timestamps.filter(Number.isFinite);
    return valid.length ? new Date(Math.max(...valid)).toISOString() : null;
  })();
  return {
    number: mapping.number,
    connectionState,
    repository: mapping.repository,
    productDecisionIssue,
    phaseIssues,
    currentPullRequests,
    phaseDiscovery: {
      ui: discoverySummary(prDiscovery.ui),
      ux: discoverySummary(prDiscovery.ux),
      backend: discoverySummary(prDiscovery.backend)
    },
    phaseVerdicts,
    activityAt,
    error: diagnostics.length ? { code: diagnostics[0], message: "Business GitHub facts are partially available." } : null
  };
}
__name(mergeBusinessFacts, "mergeBusinessFacts");
function createMergedPayload({ businessFacts, repositoryData, syncedAt, stale }) {
  return {
    ok: true,
    schemaVersion: SCHEMA_VERSION,
    syncedAt,
    stale: Boolean(stale),
    repository: repositoryData ? {
      fullName: String(repositoryData.nameWithOwner || ""),
      url: String(repositoryData.url || ""),
      defaultBranch: String(repositoryData.defaultBranchRef?.name || "main"),
      latestSha: String(repositoryData.defaultBranchRef?.target?.oid || ""),
      latestCommitTitle: String(repositoryData.defaultBranchRef?.target?.messageHeadline || ""),
      latestCommitAt: repositoryData.defaultBranchRef?.target?.committedDate || null
    } : null,
    businesses: businessFacts,
    errors: []
  };
}
__name(createMergedPayload, "createMergedPayload");
var SCHEMA_VERSION;
var PHASE_ISSUE_KEYS;
var STATIC_FALLBACK_KEYS;
var PHASES;
var init_business_fact_merger = __esm({
  "_lib/business-fact-merger.js"() {
    init_functionsRoutes_0_25189528211003487();
    init_business_verdict_parser();
    init_business_pr_discovery();
    SCHEMA_VERSION = 2;
    PHASE_ISSUE_KEYS = Object.freeze({ ui: "uiPhaseIssue", ux: "uxPhaseIssue", backend: "bePhaseIssue" });
    STATIC_FALLBACK_KEYS = Object.freeze({ ui: "uiStatus", ux: "uxStatus", backend: "backendStatus" });
    PHASES = Object.freeze(["ui", "ux", "backend"]);
    __name2(normalizeIssue, "normalizeIssue");
    __name2(discoverySummary, "discoverySummary");
    __name2(mergeBusinessFacts, "mergeBusinessFacts");
    __name2(createMergedPayload, "createMergedPayload");
  }
});
function safeError(code, message) {
  return { code, message };
}
__name(safeError, "safeError");
function jsonResponse(payload, { status = 200, head = false, headers = {} } = {}) {
  return new Response(head ? null : JSON.stringify(payload), { status, headers: { ...BASE_HEADERS, ...headers } });
}
__name(jsonResponse, "jsonResponse");
function configurationMissingPayload() {
  return {
    ok: false,
    schemaVersion: SCHEMA_VERSION,
    syncedAt: null,
    stale: false,
    error: safeError("CONFIGURATION_MISSING", "GitHub live synchronization is not configured."),
    businesses: []
  };
}
__name(configurationMissingPayload, "configurationMissingPayload");
function cacheConfigurationMissingPayload() {
  return {
    ok: false,
    schemaVersion: SCHEMA_VERSION,
    syncedAt: null,
    stale: false,
    error: safeError("CACHE_CONFIGURATION_MISSING", "GitHub live synchronization cache is not configured."),
    businesses: []
  };
}
__name(cacheConfigurationMissingPayload, "cacheConfigurationMissingPayload");
var BASE_HEADERS;
var init_response = __esm({
  "_lib/response.js"() {
    init_functionsRoutes_0_25189528211003487();
    init_business_fact_merger();
    BASE_HEADERS = {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer"
    };
    __name2(safeError, "safeError");
    __name2(jsonResponse, "jsonResponse");
    __name2(configurationMissingPayload, "configurationMissingPayload");
    __name2(cacheConfigurationMissingPayload, "cacheConfigurationMissingPayload");
  }
});
function rateLimitDetails(response) {
  return {
    retryAfter: response.headers.get("Retry-After") || null,
    resetAtEpochSeconds: response.headers.get("X-RateLimit-Reset") || null
  };
}
__name(rateLimitDetails, "rateLimitDetails");
function isRateLimitedResponse(response) {
  return response.status === 429 || response.status === 403 || response.headers.get("X-RateLimit-Remaining") === "0";
}
__name(isRateLimitedResponse, "isRateLimitedResponse");
function safeGraphQLErrors(errors) {
  return Array.isArray(errors) ? errors.map((error) => ({
    path: Array.isArray(error?.path) ? error.path.filter((part) => typeof part === "string" || Number.isInteger(part)) : [],
    type: typeof error?.type === "string" ? error.type : null
  })) : [];
}
__name(safeGraphQLErrors, "safeGraphQLErrors");
function graphQlRateLimited(errors) {
  return Array.isArray(errors) && errors.some((error) => /rate.?limit|abuse|secondary/i.test(String(error?.message || "")));
}
__name(graphQlRateLimited, "graphQlRateLimited");
var STATUS_QUERY;
var API_BASE;
var GRAPHQL_URL;
var API_VERSION2;
var ACCEPT2;
var USER_AGENT2;
var GitHubApiError;
var GitHubClient;
var init_github_client = __esm({
  "_lib/github-client.js"() {
    init_functionsRoutes_0_25189528211003487();
    init_business_github_map();
    init_business_github_query();
    init_response();
    STATUS_QUERY = buildStatusQuery({ prSearchLimit: 10 });
    API_BASE = "https://api.github.com";
    GRAPHQL_URL = `${API_BASE}/graphql`;
    API_VERSION2 = "2026-03-10";
    ACCEPT2 = "application/vnd.github+json";
    USER_AGENT2 = "ai-revenue-portfolio-console";
    GitHubApiError = class extends Error {
      static {
        __name(this, "GitHubApiError");
      }
      static {
        __name2(this, "GitHubApiError");
      }
      constructor(code, status, message = "GitHub data is temporarily unavailable.", details = {}) {
        super(message);
        this.name = "GitHubApiError";
        this.code = code;
        this.status = status;
        this.details = details;
      }
    };
    __name2(rateLimitDetails, "rateLimitDetails");
    __name2(isRateLimitedResponse, "isRateLimitedResponse");
    __name2(safeGraphQLErrors, "safeGraphQLErrors");
    __name2(graphQlRateLimited, "graphQlRateLimited");
    GitHubClient = class {
      static {
        __name(this, "GitHubClient");
      }
      static {
        __name2(this, "GitHubClient");
      }
      constructor({ authProvider, fetchImpl = fetch }) {
        this.authProvider = authProvider;
        this.fetchImpl = fetchImpl;
      }
      async graphql(repository, { retryAuth = true } = {}) {
        assertAllowedRepository(repository);
        const [owner, name] = repository.split("/");
        const token = await this.authProvider.getToken();
        const query = buildStatusQuery({ prSearchLimit: 10 });
        const response = await this.fetchImpl(GRAPHQL_URL, {
          method: "POST",
          headers: {
            Accept: ACCEPT2,
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": API_VERSION2,
            "User-Agent": USER_AGENT2
          },
          body: JSON.stringify({ query, variables: { owner, name } })
        });
        if (response.status === 401 && retryAuth) {
          this.authProvider.invalidate();
          await this.authProvider.getToken({ forceRefresh: true });
          return this.graphql(repository, { retryAuth: false });
        }
        if (isRateLimitedResponse(response)) {
          throw new GitHubApiError(
            "UPSTREAM_RATE_LIMITED",
            response.status,
            "GitHub rate limit is temporarily preventing synchronization.",
            rateLimitDetails(response)
          );
        }
        if (!response.ok) throw new GitHubApiError("GITHUB_REQUEST_FAILED", response.status);
        let payload;
        try {
          payload = await response.json();
        } catch {
          throw new GitHubApiError("GITHUB_RESPONSE_INVALID", 502);
        }
        if (graphQlRateLimited(payload?.errors)) {
          throw new GitHubApiError(
            "UPSTREAM_RATE_LIMITED",
            403,
            "GitHub rate limit is temporarily preventing synchronization."
          );
        }
        if (!payload?.data) throw new GitHubApiError("GRAPHQL_DATA_UNAVAILABLE", 502);
        return { data: payload.data, errors: safeGraphQLErrors(payload.errors) };
      }
      getStatusAggregation(repository = GITHUB_REPOSITORY) {
        return this.graphql(repository);
      }
      /** Return the Phase 2A request budget for documentation/testing */
      getRequestBudget() {
        return getRequestBudget();
      }
    };
  }
});
function validRecord(value) {
  return value && value.schemaVersion === 1 && Number.isFinite(value.storedAtMs) && (value.snapshot?.schemaVersion === 1 || value.snapshot?.schemaVersion === 2);
}
__name(validRecord, "validRecord");
function snapshotRecord(snapshot, storedAtMs) {
  return { schemaVersion: 1, snapshot, storedAtMs };
}
__name(snapshotRecord, "snapshotRecord");
var SNAPSHOT_KEY;
var DEFAULT_EXPIRATION_TTL;
var runtimeMemory;
var RuntimeSnapshotCache;
var init_cache = __esm({
  "_lib/cache.js"() {
    init_functionsRoutes_0_25189528211003487();
    SNAPSHOT_KEY = "github-status:v1:last-good";
    DEFAULT_EXPIRATION_TTL = 86400;
    runtimeMemory = /* @__PURE__ */ new Map();
    __name2(validRecord, "validRecord");
    __name2(snapshotRecord, "snapshotRecord");
    RuntimeSnapshotCache = class {
      static {
        __name(this, "RuntimeSnapshotCache");
      }
      static {
        __name2(this, "RuntimeSnapshotCache");
      }
      constructor({ kv, now = /* @__PURE__ */ __name2(() => Date.now(), "now"), memoryStore = runtimeMemory, expirationTtl = DEFAULT_EXPIRATION_TTL } = {}) {
        this.kv = kv;
        this.now = now;
        this.memoryStore = memoryStore;
        this.expirationTtl = expirationTtl;
      }
      async get() {
        const memory = this.memoryStore.get(SNAPSHOT_KEY);
        if (validRecord(memory)) return memory;
        if (!this.kv?.get) return null;
        try {
          const value = await this.kv.get(SNAPSHOT_KEY, { type: "json", cacheTtl: 30 });
          if (!validRecord(value)) return null;
          this.memoryStore.set(SNAPSHOT_KEY, value);
          return value;
        } catch {
          return null;
        }
      }
      setMemory(snapshot) {
        const value = snapshotRecord(snapshot, this.now());
        this.memoryStore.set(SNAPSHOT_KEY, value);
        return value;
      }
      async persist(record) {
        if (!this.kv?.put) throw new Error("KV cache binding is unavailable.");
        if (!validRecord(record)) throw new Error("Snapshot cache record is invalid.");
        await this.kv.put(SNAPSHOT_KEY, JSON.stringify(record), { expirationTtl: this.expirationTtl });
        return { persisted: true, errorCode: null };
      }
      async set(snapshot) {
        const record = this.setMemory(snapshot);
        try {
          return await this.persist(record);
        } catch {
          return { persisted: false, errorCode: "CACHE_WRITE_FAILED" };
        }
      }
    };
  }
});
function errorPaths(errors) {
  return (errors || []).map((e) => Array.isArray(e.path) ? e.path.map(String) : []);
}
__name(errorPaths, "errorPaths");
function upstreamErrorResult(error, cached, ageMs, staleTtlSeconds) {
  const rateLimited = error instanceof GitHubApiError && error.code === "UPSTREAM_RATE_LIMITED";
  const code = rateLimited ? "UPSTREAM_RATE_LIMITED" : "UPSTREAM_UNAVAILABLE";
  if (cached && ageMs <= staleTtlSeconds * 1e3) {
    return {
      payload: { ...cached.snapshot, ok: true, stale: true, errors: [...cached.snapshot.errors || [], safeError(code, rateLimited ? "GitHub rate limits prevented refresh; showing the last successful snapshot." : "GitHub data could not be refreshed; showing the last successful snapshot.")] },
      status: 200,
      cacheState: "stale"
    };
  }
  return {
    payload: { ok: false, schemaVersion: SCHEMA_VERSION, syncedAt: null, stale: false, error: safeError(code, rateLimited ? "GitHub rate limits are temporarily preventing synchronization." : "GitHub data is temporarily unavailable."), businesses: [] },
    status: rateLimited ? 503 : 502,
    cacheState: "unavailable"
  };
}
__name(upstreamErrorResult, "upstreamErrorResult");
function createGitHubStatusService({
  client,
  cache,
  now = /* @__PURE__ */ __name2(() => Date.now(), "now"),
  freshTtlSeconds = 180,
  staleTtlSeconds = 86400,
  singleFlightKey = GITHUB_REPOSITORY,
  identitySource = null
  // Map<number, {uiStatus, uxStatus, backendStatus}>
}) {
  async function loadFresh() {
    const aggregate = await client.getStatusAggregation(GITHUB_REPOSITORY);
    const root = aggregate?.data || {};
    const repositoryData = root.repository;
    if (!repositoryData) throw new GitHubApiError("GRAPHQL_DATA_UNAVAILABLE", 502);
    const paths = errorPaths(aggregate.errors);
    const phaseIssueResults = {};
    const mappedEntries = BUSINESS_GITHUB_MAP.filter((m) => m.repository === GITHUB_REPOSITORY);
    for (const m of mappedEntries) {
      for (const phase of ["uiPhaseIssue", "uxPhaseIssue", "bePhaseIssue"]) {
        const issueNum = m[phase];
        if (!issueNum || phaseIssueResults[`prSearch${issueNum}`]) continue;
        const [refsAlias, relatedAlias] = getPrSearchAliases(issueNum);
        const refsResult = root[refsAlias] || { nodes: [] };
        const relatedResult = root[relatedAlias] || { nodes: [] };
        const seen = /* @__PURE__ */ new Set();
        const nodes = [];
        for (const node of [...refsResult.nodes || [], ...relatedResult.nodes || []]) {
          const prNumber = Number(node?.number);
          if (!Number.isInteger(prNumber) || seen.has(prNumber)) continue;
          seen.add(prNumber);
          nodes.push(node);
        }
        const truncated = Number(refsResult.issueCount || 0) > (refsResult.nodes || []).length || Number(relatedResult.issueCount || 0) > (relatedResult.nodes || []).length;
        phaseIssueResults[`prSearch${issueNum}`] = { nodes, truncated };
      }
    }
    const businessFacts = mappedEntries.map((mapping) => mergeBusinessFacts({
      mapping,
      repositoryData,
      phaseIssueResults,
      fallbackPrNode: mapping.fallbackPrNumber ? repositoryData[`fallbackPr${mapping.fallbackPrNumber}`] : null,
      identitySource
    }));
    const errors = [];
    for (const fact of businessFacts) {
      if (fact.error) errors.push({ businessNumber: fact.number, code: fact.error.code, message: fact.error.message });
    }
    if ((aggregate.errors || []).length && errors.length === 0) {
      errors.push(safeError("GRAPHQL_PARTIAL", "Some GitHub fields are unavailable."));
    }
    const merged = createMergedPayload({ businessFacts, repositoryData, syncedAt: new Date(now()).toISOString(), stale: false });
    merged.errors = errors;
    return merged;
  }
  __name(loadFresh, "loadFresh");
  __name2(loadFresh, "loadFresh");
  async function storeFreshSnapshot(snapshot) {
    let result;
    try {
      result = await cache.set(snapshot);
    } catch {
      result = { persisted: false, errorCode: "CACHE_WRITE_FAILED" };
    }
    if (result?.persisted !== false) return snapshot;
    const degraded = { ...snapshot, errors: [...snapshot.errors || [], safeError("CACHE_WRITE_FAILED", "The latest GitHub snapshot could not be persisted.")] };
    if (typeof cache.setMemory === "function") cache.setMemory(degraded);
    return degraded;
  }
  __name(storeFreshSnapshot, "storeFreshSnapshot");
  __name2(storeFreshSnapshot, "storeFreshSnapshot");
  async function refreshSingleFlight() {
    const existing = refreshFlights.get(singleFlightKey);
    if (existing) return existing;
    const flight = (async () => storeFreshSnapshot(await loadFresh()))();
    refreshFlights.set(singleFlightKey, flight);
    try {
      return await flight;
    } finally {
      if (refreshFlights.get(singleFlightKey) === flight) refreshFlights.delete(singleFlightKey);
    }
  }
  __name(refreshSingleFlight, "refreshSingleFlight");
  __name2(refreshSingleFlight, "refreshSingleFlight");
  return {
    async getStatus() {
      const cached = await cache.get();
      const ageMs = cached ? now() - cached.storedAtMs : Number.POSITIVE_INFINITY;
      if (cached && ageMs <= freshTtlSeconds * 1e3) return { payload: { ...cached.snapshot, stale: false }, status: 200, cacheState: "fresh" };
      try {
        const snapshot = await refreshSingleFlight();
        return { payload: snapshot, status: 200, cacheState: "miss" };
      } catch (error) {
        return upstreamErrorResult(error, cached, ageMs, staleTtlSeconds);
      }
    }
  };
}
__name(createGitHubStatusService, "createGitHubStatusService");
var refreshFlights;
var init_github_status_service = __esm({
  "_lib/github-status-service.js"() {
    init_functionsRoutes_0_25189528211003487();
    init_business_github_map();
    init_github_client();
    init_business_github_query();
    init_business_fact_merger();
    init_response();
    refreshFlights = /* @__PURE__ */ new Map();
    __name2(errorPaths, "errorPaths");
    __name2(upstreamErrorResult, "upstreamErrorResult");
    __name2(createGitHubStatusService, "createGitHubStatusService");
  }
});
var require_business_identity_core = __commonJS({
  "../business-identity-core.js"(exports, module) {
    init_functionsRoutes_0_25189528211003487();
    (function(root, factory) {
      var api = factory();
      if (typeof module === "object" && module.exports) module.exports = api;
      root.ARL_IDENTITY_CORE = api;
    })(typeof globalThis !== "undefined" ? globalThis : exports, function() {
      "use strict";
      var BUSINESS_PHASE_AUTHORITY2 = Object.freeze([
        // n, ui, ux, be
        { n: 1, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 2, ui: "UI_APPROVED", ux: "NOT_STARTED", be: "IMPLEMENTED" },
        { n: 3, ui: "UI_APPROVED", ux: "NOT_STARTED", be: "IMPLEMENTED" },
        { n: 4, ui: "UI_APPROVED", ux: "NOT_STARTED", be: "NOT_APPLICABLE" },
        { n: 5, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 6, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 7, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 8, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 9, ui: "UI_APPROVED", ux: "NOT_STARTED", be: "FROZEN" },
        { n: 10, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 11, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 12, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 13, ui: "UI_APPROVED", ux: "NOT_STARTED", be: "DECISION_PENDING" },
        { n: 14, ui: "UI_APPROVED", ux: "NOT_STARTED", be: "IN_PROGRESS" },
        { n: 15, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 16, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 17, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 18, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 19, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 20, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 21, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 22, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 23, ui: "UI_APPROVED", ux: "IN_PROGRESS", be: "IMPLEMENTED" },
        { n: 24, ui: "UI_APPROVED", ux: "NOT_STARTED", be: "IMPLEMENTED" },
        { n: 25, ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 26, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 27, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 28, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 29, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 30, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 31, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 32, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 33, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 34, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 35, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 36, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 37, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 38, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 39, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 40, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 41, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 42, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 43, ui: "IN_PROGRESS", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 44, ui: "UI_APPROVED", ux: "NOT_STARTED", be: "IMPLEMENTED" },
        { n: 45, ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 46, ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 47, ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 48, ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 49, ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 50, ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 51, ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 52, ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 53, ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 54, ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" },
        { n: 55, ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" }
      ]);
      var byNumber = {};
      for (var i = 0; i < BUSINESS_PHASE_AUTHORITY2.length; i++) {
        byNumber[BUSINESS_PHASE_AUTHORITY2[i].n] = BUSINESS_PHASE_AUTHORITY2[i];
      }
      function phaseStatusFor(number) {
        var entry = byNumber[Number(number)];
        if (!entry) return { ui: "NOT_STARTED", ux: "BLOCKED_BY_UI", be: "FROZEN" };
        return { ui: entry.ui, ux: entry.ux, be: entry.be };
      }
      __name(phaseStatusFor, "phaseStatusFor");
      __name2(phaseStatusFor, "phaseStatusFor");
      function buildIdentitySource2() {
        var map = {};
        for (var i2 = 0; i2 < BUSINESS_PHASE_AUTHORITY2.length; i2++) {
          var entry = BUSINESS_PHASE_AUTHORITY2[i2];
          map[entry.n] = { uiStatus: entry.ui, uxStatus: entry.ux, backendStatus: entry.be };
        }
        return map;
      }
      __name(buildIdentitySource2, "buildIdentitySource2");
      __name2(buildIdentitySource2, "buildIdentitySource");
      return {
        BUSINESS_PHASE_AUTHORITY: BUSINESS_PHASE_AUTHORITY2,
        phaseStatusFor,
        buildIdentitySource: buildIdentitySource2
      };
    });
  }
});
function buildIdentitySource() {
  return import_business_identity_core.default.buildIdentitySource();
}
__name(buildIdentitySource, "buildIdentitySource");
var import_business_identity_core;
var BUSINESS_PHASE_AUTHORITY;
var init_business_identity_data = __esm({
  "../business-identity-data.js"() {
    init_functionsRoutes_0_25189528211003487();
    import_business_identity_core = __toESM(require_business_identity_core());
    BUSINESS_PHASE_AUTHORITY = import_business_identity_core.default.BUSINESS_PHASE_AUTHORITY;
    __name2(buildIdentitySource, "buildIdentitySource");
  }
});
function hasConfiguration(env) {
  return REQUIRED_BINDINGS.every((name) => typeof env?.[name] === "string" && env[name].trim());
}
__name(hasConfiguration, "hasConfiguration");
function hasSnapshotCache(env) {
  return Boolean(env?.GITHUB_STATUS_SNAPSHOT_KV?.get && env?.GITHUB_STATUS_SNAPSHOT_KV?.put);
}
__name(hasSnapshotCache, "hasSnapshotCache");
function failure(code, message) {
  return { ok: false, schemaVersion: SCHEMA_VERSION, syncedAt: null, stale: false, error: safeError(code, message), businesses: [] };
}
__name(failure, "failure");
async function handleGitHubStatusRequest({
  request,
  env = {},
  fetchImpl = fetch,
  cache,
  now = /* @__PURE__ */ __name2(() => Date.now(), "now"),
  cryptoImpl = globalThis.crypto,
  client: injectedClient = null
}) {
  const method = String(request.method || "GET").toUpperCase();
  const isHead = method === "HEAD";
  if (method !== "GET" && !isHead) {
    return jsonResponse(failure("METHOD_NOT_ALLOWED", "Only GET and HEAD are supported."), { status: 405, headers: { Allow: "GET, HEAD" } });
  }
  const url = new URL(request.url);
  if ([...url.searchParams.keys()].length > 0) {
    return jsonResponse(failure("INVALID_QUERY", "Query parameters are not supported."), { status: 400, head: isHead });
  }
  if (!hasConfiguration(env)) {
    return jsonResponse(configurationMissingPayload(), { status: 503, head: isHead });
  }
  if (!cache && !hasSnapshotCache(env)) {
    return jsonResponse(cacheConfigurationMissingPayload(), { status: 503, head: isHead });
  }
  try {
    const authProvider = injectedClient ? null : new InstallationTokenProvider({
      appId: env.GITHUB_APP_ID,
      installationId: env.GITHUB_APP_INSTALLATION_ID,
      privateKeyPkcs8: env.GITHUB_APP_PRIVATE_KEY_PKCS8,
      fetchImpl,
      now,
      cryptoImpl
    });
    const client = injectedClient || new GitHubClient({ authProvider, fetchImpl });
    const snapshotCache = cache || new RuntimeSnapshotCache({ kv: env.GITHUB_STATUS_SNAPSHOT_KV, now });
    const identitySource = buildIdentitySource();
    const result = await createGitHubStatusService({ client, cache: snapshotCache, now, identitySource }).getStatus();
    return jsonResponse(result.payload, {
      status: result.status,
      head: isHead,
      headers: { "X-Portfolio-Cache": result.cacheState }
    });
  } catch {
    return jsonResponse(failure("INTERNAL_ERROR", "GitHub live synchronization could not be completed."), { status: 500, head: isHead });
  }
}
__name(handleGitHubStatusRequest, "handleGitHubStatusRequest");
async function onRequest(context) {
  return handleGitHubStatusRequest({ request: context.request, env: context.env });
}
__name(onRequest, "onRequest");
var REQUIRED_BINDINGS;
var init_github_status = __esm({
  "api/github-status.js"() {
    init_functionsRoutes_0_25189528211003487();
    init_github_app_auth();
    init_github_client();
    init_cache();
    init_github_status_service();
    init_response();
    init_business_fact_merger();
    init_business_identity_data();
    REQUIRED_BINDINGS = ["GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID", "GITHUB_APP_PRIVATE_KEY_PKCS8"];
    __name2(hasConfiguration, "hasConfiguration");
    __name2(hasSnapshotCache, "hasSnapshotCache");
    __name2(failure, "failure");
    __name2(handleGitHubStatusRequest, "handleGitHubStatusRequest");
    __name2(onRequest, "onRequest");
  }
});
var routes;
var init_functionsRoutes_0_25189528211003487 = __esm({
  "../.wrangler/tmp/pages-Y1G9U5/functionsRoutes-0.25189528211003487.mjs"() {
    init_github_status();
    routes = [
      {
        routePath: "/api/github-status",
        mountPath: "/api",
        method: "",
        middlewares: [],
        modules: [onRequest]
      }
    ];
  }
});
init_functionsRoutes_0_25189528211003487();
init_functionsRoutes_0_25189528211003487();
init_functionsRoutes_0_25189528211003487();
init_functionsRoutes_0_25189528211003487();
function lexer(str) {
  var tokens = [];
  var i = 0;
  while (i < str.length) {
    var char = str[i];
    if (char === "*" || char === "+" || char === "?") {
      tokens.push({ type: "MODIFIER", index: i, value: str[i++] });
      continue;
    }
    if (char === "\\") {
      tokens.push({ type: "ESCAPED_CHAR", index: i++, value: str[i++] });
      continue;
    }
    if (char === "{") {
      tokens.push({ type: "OPEN", index: i, value: str[i++] });
      continue;
    }
    if (char === "}") {
      tokens.push({ type: "CLOSE", index: i, value: str[i++] });
      continue;
    }
    if (char === ":") {
      var name = "";
      var j = i + 1;
      while (j < str.length) {
        var code = str.charCodeAt(j);
        if (
          // `0-9`
          code >= 48 && code <= 57 || // `A-Z`
          code >= 65 && code <= 90 || // `a-z`
          code >= 97 && code <= 122 || // `_`
          code === 95
        ) {
          name += str[j++];
          continue;
        }
        break;
      }
      if (!name)
        throw new TypeError("Missing parameter name at ".concat(i));
      tokens.push({ type: "NAME", index: i, value: name });
      i = j;
      continue;
    }
    if (char === "(") {
      var count = 1;
      var pattern = "";
      var j = i + 1;
      if (str[j] === "?") {
        throw new TypeError('Pattern cannot start with "?" at '.concat(j));
      }
      while (j < str.length) {
        if (str[j] === "\\") {
          pattern += str[j++] + str[j++];
          continue;
        }
        if (str[j] === ")") {
          count--;
          if (count === 0) {
            j++;
            break;
          }
        } else if (str[j] === "(") {
          count++;
          if (str[j + 1] !== "?") {
            throw new TypeError("Capturing groups are not allowed at ".concat(j));
          }
        }
        pattern += str[j++];
      }
      if (count)
        throw new TypeError("Unbalanced pattern at ".concat(i));
      if (!pattern)
        throw new TypeError("Missing pattern at ".concat(i));
      tokens.push({ type: "PATTERN", index: i, value: pattern });
      i = j;
      continue;
    }
    tokens.push({ type: "CHAR", index: i, value: str[i++] });
  }
  tokens.push({ type: "END", index: i, value: "" });
  return tokens;
}
__name(lexer, "lexer");
__name2(lexer, "lexer");
function parse(str, options) {
  if (options === void 0) {
    options = {};
  }
  var tokens = lexer(str);
  var _a = options.prefixes, prefixes = _a === void 0 ? "./" : _a, _b = options.delimiter, delimiter = _b === void 0 ? "/#?" : _b;
  var result = [];
  var key = 0;
  var i = 0;
  var path = "";
  var tryConsume = /* @__PURE__ */ __name2(function(type) {
    if (i < tokens.length && tokens[i].type === type)
      return tokens[i++].value;
  }, "tryConsume");
  var mustConsume = /* @__PURE__ */ __name2(function(type) {
    var value2 = tryConsume(type);
    if (value2 !== void 0)
      return value2;
    var _a2 = tokens[i], nextType = _a2.type, index = _a2.index;
    throw new TypeError("Unexpected ".concat(nextType, " at ").concat(index, ", expected ").concat(type));
  }, "mustConsume");
  var consumeText = /* @__PURE__ */ __name2(function() {
    var result2 = "";
    var value2;
    while (value2 = tryConsume("CHAR") || tryConsume("ESCAPED_CHAR")) {
      result2 += value2;
    }
    return result2;
  }, "consumeText");
  var isSafe = /* @__PURE__ */ __name2(function(value2) {
    for (var _i = 0, delimiter_1 = delimiter; _i < delimiter_1.length; _i++) {
      var char2 = delimiter_1[_i];
      if (value2.indexOf(char2) > -1)
        return true;
    }
    return false;
  }, "isSafe");
  var safePattern = /* @__PURE__ */ __name2(function(prefix2) {
    var prev = result[result.length - 1];
    var prevText = prefix2 || (prev && typeof prev === "string" ? prev : "");
    if (prev && !prevText) {
      throw new TypeError('Must have text between two parameters, missing text after "'.concat(prev.name, '"'));
    }
    if (!prevText || isSafe(prevText))
      return "[^".concat(escapeString(delimiter), "]+?");
    return "(?:(?!".concat(escapeString(prevText), ")[^").concat(escapeString(delimiter), "])+?");
  }, "safePattern");
  while (i < tokens.length) {
    var char = tryConsume("CHAR");
    var name = tryConsume("NAME");
    var pattern = tryConsume("PATTERN");
    if (name || pattern) {
      var prefix = char || "";
      if (prefixes.indexOf(prefix) === -1) {
        path += prefix;
        prefix = "";
      }
      if (path) {
        result.push(path);
        path = "";
      }
      result.push({
        name: name || key++,
        prefix,
        suffix: "",
        pattern: pattern || safePattern(prefix),
        modifier: tryConsume("MODIFIER") || ""
      });
      continue;
    }
    var value = char || tryConsume("ESCAPED_CHAR");
    if (value) {
      path += value;
      continue;
    }
    if (path) {
      result.push(path);
      path = "";
    }
    var open = tryConsume("OPEN");
    if (open) {
      var prefix = consumeText();
      var name_1 = tryConsume("NAME") || "";
      var pattern_1 = tryConsume("PATTERN") || "";
      var suffix = consumeText();
      mustConsume("CLOSE");
      result.push({
        name: name_1 || (pattern_1 ? key++ : ""),
        pattern: name_1 && !pattern_1 ? safePattern(prefix) : pattern_1,
        prefix,
        suffix,
        modifier: tryConsume("MODIFIER") || ""
      });
      continue;
    }
    mustConsume("END");
  }
  return result;
}
__name(parse, "parse");
__name2(parse, "parse");
function match(str, options) {
  var keys = [];
  var re = pathToRegexp(str, keys, options);
  return regexpToFunction(re, keys, options);
}
__name(match, "match");
__name2(match, "match");
function regexpToFunction(re, keys, options) {
  if (options === void 0) {
    options = {};
  }
  var _a = options.decode, decode = _a === void 0 ? function(x) {
    return x;
  } : _a;
  return function(pathname) {
    var m = re.exec(pathname);
    if (!m)
      return false;
    var path = m[0], index = m.index;
    var params = /* @__PURE__ */ Object.create(null);
    var _loop_1 = /* @__PURE__ */ __name2(function(i2) {
      if (m[i2] === void 0)
        return "continue";
      var key = keys[i2 - 1];
      if (key.modifier === "*" || key.modifier === "+") {
        params[key.name] = m[i2].split(key.prefix + key.suffix).map(function(value) {
          return decode(value, key);
        });
      } else {
        params[key.name] = decode(m[i2], key);
      }
    }, "_loop_1");
    for (var i = 1; i < m.length; i++) {
      _loop_1(i);
    }
    return { path, index, params };
  };
}
__name(regexpToFunction, "regexpToFunction");
__name2(regexpToFunction, "regexpToFunction");
function escapeString(str) {
  return str.replace(/([.+*?=^!:${}()[\]|/\\])/g, "\\$1");
}
__name(escapeString, "escapeString");
__name2(escapeString, "escapeString");
function flags(options) {
  return options && options.sensitive ? "" : "i";
}
__name(flags, "flags");
__name2(flags, "flags");
function regexpToRegexp(path, keys) {
  if (!keys)
    return path;
  var groupsRegex = /\((?:\?<(.*?)>)?(?!\?)/g;
  var index = 0;
  var execResult = groupsRegex.exec(path.source);
  while (execResult) {
    keys.push({
      // Use parenthesized substring match if available, index otherwise
      name: execResult[1] || index++,
      prefix: "",
      suffix: "",
      modifier: "",
      pattern: ""
    });
    execResult = groupsRegex.exec(path.source);
  }
  return path;
}
__name(regexpToRegexp, "regexpToRegexp");
__name2(regexpToRegexp, "regexpToRegexp");
function arrayToRegexp(paths, keys, options) {
  var parts = paths.map(function(path) {
    return pathToRegexp(path, keys, options).source;
  });
  return new RegExp("(?:".concat(parts.join("|"), ")"), flags(options));
}
__name(arrayToRegexp, "arrayToRegexp");
__name2(arrayToRegexp, "arrayToRegexp");
function stringToRegexp(path, keys, options) {
  return tokensToRegexp(parse(path, options), keys, options);
}
__name(stringToRegexp, "stringToRegexp");
__name2(stringToRegexp, "stringToRegexp");
function tokensToRegexp(tokens, keys, options) {
  if (options === void 0) {
    options = {};
  }
  var _a = options.strict, strict = _a === void 0 ? false : _a, _b = options.start, start = _b === void 0 ? true : _b, _c = options.end, end = _c === void 0 ? true : _c, _d = options.encode, encode = _d === void 0 ? function(x) {
    return x;
  } : _d, _e = options.delimiter, delimiter = _e === void 0 ? "/#?" : _e, _f = options.endsWith, endsWith = _f === void 0 ? "" : _f;
  var endsWithRe = "[".concat(escapeString(endsWith), "]|$");
  var delimiterRe = "[".concat(escapeString(delimiter), "]");
  var route = start ? "^" : "";
  for (var _i = 0, tokens_1 = tokens; _i < tokens_1.length; _i++) {
    var token = tokens_1[_i];
    if (typeof token === "string") {
      route += escapeString(encode(token));
    } else {
      var prefix = escapeString(encode(token.prefix));
      var suffix = escapeString(encode(token.suffix));
      if (token.pattern) {
        if (keys)
          keys.push(token);
        if (prefix || suffix) {
          if (token.modifier === "+" || token.modifier === "*") {
            var mod = token.modifier === "*" ? "?" : "";
            route += "(?:".concat(prefix, "((?:").concat(token.pattern, ")(?:").concat(suffix).concat(prefix, "(?:").concat(token.pattern, "))*)").concat(suffix, ")").concat(mod);
          } else {
            route += "(?:".concat(prefix, "(").concat(token.pattern, ")").concat(suffix, ")").concat(token.modifier);
          }
        } else {
          if (token.modifier === "+" || token.modifier === "*") {
            throw new TypeError('Can not repeat "'.concat(token.name, '" without a prefix and suffix'));
          }
          route += "(".concat(token.pattern, ")").concat(token.modifier);
        }
      } else {
        route += "(?:".concat(prefix).concat(suffix, ")").concat(token.modifier);
      }
    }
  }
  if (end) {
    if (!strict)
      route += "".concat(delimiterRe, "?");
    route += !options.endsWith ? "$" : "(?=".concat(endsWithRe, ")");
  } else {
    var endToken = tokens[tokens.length - 1];
    var isEndDelimited = typeof endToken === "string" ? delimiterRe.indexOf(endToken[endToken.length - 1]) > -1 : endToken === void 0;
    if (!strict) {
      route += "(?:".concat(delimiterRe, "(?=").concat(endsWithRe, "))?");
    }
    if (!isEndDelimited) {
      route += "(?=".concat(delimiterRe, "|").concat(endsWithRe, ")");
    }
  }
  return new RegExp(route, flags(options));
}
__name(tokensToRegexp, "tokensToRegexp");
__name2(tokensToRegexp, "tokensToRegexp");
function pathToRegexp(path, keys, options) {
  if (path instanceof RegExp)
    return regexpToRegexp(path, keys);
  if (Array.isArray(path))
    return arrayToRegexp(path, keys, options);
  return stringToRegexp(path, keys, options);
}
__name(pathToRegexp, "pathToRegexp");
__name2(pathToRegexp, "pathToRegexp");
var escapeRegex = /[.+?^${}()|[\]\\]/g;
function* executeRequest(request) {
  const requestPath = new URL(request.url).pathname;
  for (const route of [...routes].reverse()) {
    if (route.method && route.method !== request.method) {
      continue;
    }
    const routeMatcher = match(route.routePath.replace(escapeRegex, "\\$&"), {
      end: false
    });
    const mountMatcher = match(route.mountPath.replace(escapeRegex, "\\$&"), {
      end: false
    });
    const matchResult = routeMatcher(requestPath);
    const mountMatchResult = mountMatcher(requestPath);
    if (matchResult && mountMatchResult) {
      for (const handler of route.middlewares.flat()) {
        yield {
          handler,
          params: matchResult.params,
          path: mountMatchResult.path
        };
      }
    }
  }
  for (const route of routes) {
    if (route.method && route.method !== request.method) {
      continue;
    }
    const routeMatcher = match(route.routePath.replace(escapeRegex, "\\$&"), {
      end: true
    });
    const mountMatcher = match(route.mountPath.replace(escapeRegex, "\\$&"), {
      end: false
    });
    const matchResult = routeMatcher(requestPath);
    const mountMatchResult = mountMatcher(requestPath);
    if (matchResult && mountMatchResult && route.modules.length) {
      for (const handler of route.modules.flat()) {
        yield {
          handler,
          params: matchResult.params,
          path: matchResult.path
        };
      }
      break;
    }
  }
}
__name(executeRequest, "executeRequest");
__name2(executeRequest, "executeRequest");
var pages_template_worker_default = {
  async fetch(originalRequest, env, workerContext) {
    let request = originalRequest;
    const handlerIterator = executeRequest(request);
    let data = {};
    let isFailOpen = false;
    const next = /* @__PURE__ */ __name2(async (input, init) => {
      if (input !== void 0) {
        let url = input;
        if (typeof input === "string") {
          url = new URL(input, request.url).toString();
        }
        request = new Request(url, init);
      }
      const result = handlerIterator.next();
      if (result.done === false) {
        const { handler, params, path } = result.value;
        const context = {
          request: new Request(request.clone()),
          functionPath: path,
          next,
          params,
          get data() {
            return data;
          },
          set data(value) {
            if (typeof value !== "object" || value === null) {
              throw new Error("context.data must be an object");
            }
            data = value;
          },
          env,
          waitUntil: workerContext.waitUntil.bind(workerContext),
          passThroughOnException: /* @__PURE__ */ __name2(() => {
            isFailOpen = true;
          }, "passThroughOnException")
        };
        const response = await handler(context);
        if (!(response instanceof Response)) {
          throw new Error("Your Pages function should return a Response");
        }
        return cloneResponse(response);
      } else if ("ASSETS") {
        const response = await env["ASSETS"].fetch(request);
        return cloneResponse(response);
      } else {
        const response = await fetch(request);
        return cloneResponse(response);
      }
    }, "next");
    try {
      return await next();
    } catch (error) {
      if (isFailOpen) {
        const response = await env["ASSETS"].fetch(request);
        return cloneResponse(response);
      }
      throw error;
    }
  }
};
var cloneResponse = /* @__PURE__ */ __name2((response) => (
  // https://fetch.spec.whatwg.org/#null-body-status
  new Response(
    [101, 204, 205, 304].includes(response.status) ? null : response.body,
    response
  )
), "cloneResponse");
init_functionsRoutes_0_25189528211003487();
var drainBody = /* @__PURE__ */ __name2(async (request, env, _ctx, middlewareCtx) => {
  try {
    return await middlewareCtx.next(request, env);
  } finally {
    try {
      if (request.body !== null && !request.bodyUsed) {
        const reader = request.body.getReader();
        while (!(await reader.read()).done) {
        }
      }
    } catch (e) {
      console.error("Failed to drain the unused request body.", e);
    }
  }
}, "drainBody");
var middleware_ensure_req_body_drained_default = drainBody;
init_functionsRoutes_0_25189528211003487();
function reduceError(e) {
  return {
    name: e?.name,
    message: e?.message ?? String(e),
    stack: e?.stack,
    cause: e?.cause === void 0 ? void 0 : reduceError(e.cause)
  };
}
__name(reduceError, "reduceError");
__name2(reduceError, "reduceError");
var jsonError = /* @__PURE__ */ __name2(async (request, env, _ctx, middlewareCtx) => {
  try {
    return await middlewareCtx.next(request, env);
  } catch (e) {
    const error = reduceError(e);
    const body = JSON.stringify(error);
    const headers = {
      "Content-Type": "application/json",
      "MF-Experimental-Error-Stack": "true"
    };
    const encoded = encodeURIComponent(body);
    if (encoded.length <= 8192) {
      headers["MF-Experimental-Error-Stack-Payload"] = encoded;
    }
    return new Response(body, { status: 500, headers });
  }
}, "jsonError");
var middleware_miniflare3_json_error_default = jsonError;
var __INTERNAL_WRANGLER_MIDDLEWARE__ = [
  middleware_ensure_req_body_drained_default,
  middleware_miniflare3_json_error_default
];
var middleware_insertion_facade_default = pages_template_worker_default;
init_functionsRoutes_0_25189528211003487();
var __facade_middleware__ = [];
function __facade_register__(...args) {
  __facade_middleware__.push(...args.flat());
}
__name(__facade_register__, "__facade_register__");
__name2(__facade_register__, "__facade_register__");
function __facade_invokeChain__(request, env, ctx, dispatch, middlewareChain) {
  const [head, ...tail] = middlewareChain;
  const middlewareCtx = {
    dispatch,
    next(newRequest, newEnv) {
      return __facade_invokeChain__(newRequest, newEnv, ctx, dispatch, tail);
    }
  };
  return head(request, env, ctx, middlewareCtx);
}
__name(__facade_invokeChain__, "__facade_invokeChain__");
__name2(__facade_invokeChain__, "__facade_invokeChain__");
function __facade_invoke__(request, env, ctx, dispatch, finalMiddleware) {
  return __facade_invokeChain__(request, env, ctx, dispatch, [
    ...__facade_middleware__,
    finalMiddleware
  ]);
}
__name(__facade_invoke__, "__facade_invoke__");
__name2(__facade_invoke__, "__facade_invoke__");
var __Facade_ScheduledController__ = class ___Facade_ScheduledController__ {
  static {
    __name(this, "___Facade_ScheduledController__");
  }
  constructor(scheduledTime, cron, noRetry) {
    this.scheduledTime = scheduledTime;
    this.cron = cron;
    this.#noRetry = noRetry;
  }
  scheduledTime;
  cron;
  static {
    __name2(this, "__Facade_ScheduledController__");
  }
  #noRetry;
  noRetry() {
    if (!(this instanceof ___Facade_ScheduledController__)) {
      throw new TypeError("Illegal invocation");
    }
    this.#noRetry();
  }
};
function wrapExportedHandler(worker) {
  if (__INTERNAL_WRANGLER_MIDDLEWARE__ === void 0 || __INTERNAL_WRANGLER_MIDDLEWARE__.length === 0) {
    return worker;
  }
  for (const middleware of __INTERNAL_WRANGLER_MIDDLEWARE__) {
    __facade_register__(middleware);
  }
  const fetchDispatcher = /* @__PURE__ */ __name2(function(request, env, ctx) {
    if (worker.fetch === void 0) {
      throw new Error("Handler does not export a fetch() function.");
    }
    return worker.fetch(request, env, ctx);
  }, "fetchDispatcher");
  return {
    ...worker,
    fetch(request, env, ctx) {
      const dispatcher = /* @__PURE__ */ __name2(function(type, init) {
        if (type === "scheduled" && worker.scheduled !== void 0) {
          const controller = new __Facade_ScheduledController__(
            Date.now(),
            init.cron ?? "",
            () => {
            }
          );
          return worker.scheduled(controller, env, ctx);
        }
      }, "dispatcher");
      return __facade_invoke__(request, env, ctx, dispatcher, fetchDispatcher);
    }
  };
}
__name(wrapExportedHandler, "wrapExportedHandler");
__name2(wrapExportedHandler, "wrapExportedHandler");
function wrapWorkerEntrypoint(klass) {
  if (__INTERNAL_WRANGLER_MIDDLEWARE__ === void 0 || __INTERNAL_WRANGLER_MIDDLEWARE__.length === 0) {
    return klass;
  }
  for (const middleware of __INTERNAL_WRANGLER_MIDDLEWARE__) {
    __facade_register__(middleware);
  }
  return class extends klass {
    #fetchDispatcher = /* @__PURE__ */ __name2((request, env, ctx) => {
      this.env = env;
      this.ctx = ctx;
      if (super.fetch === void 0) {
        throw new Error("Entrypoint class does not define a fetch() function.");
      }
      return super.fetch(request);
    }, "#fetchDispatcher");
    #dispatcher = /* @__PURE__ */ __name2((type, init) => {
      if (type === "scheduled" && super.scheduled !== void 0) {
        const controller = new __Facade_ScheduledController__(
          Date.now(),
          init.cron ?? "",
          () => {
          }
        );
        return super.scheduled(controller);
      }
    }, "#dispatcher");
    fetch(request) {
      return __facade_invoke__(
        request,
        this.env,
        this.ctx,
        this.#dispatcher,
        this.#fetchDispatcher
      );
    }
  };
}
__name(wrapWorkerEntrypoint, "wrapWorkerEntrypoint");
__name2(wrapWorkerEntrypoint, "wrapWorkerEntrypoint");
var WRAPPED_ENTRY;
if (typeof middleware_insertion_facade_default === "object") {
  WRAPPED_ENTRY = wrapExportedHandler(middleware_insertion_facade_default);
} else if (typeof middleware_insertion_facade_default === "function") {
  WRAPPED_ENTRY = wrapWorkerEntrypoint(middleware_insertion_facade_default);
}
var middleware_loader_entry_default = WRAPPED_ENTRY;

// ../../../../../../../../../root/.nvm/versions/node/v22.23.1/lib/node_modules/wrangler/templates/pages-dev-util.ts
function isRoutingRuleMatch(pathname, routingRule) {
  if (!pathname) {
    throw new Error("Pathname is undefined.");
  }
  if (!routingRule) {
    throw new Error("Routing rule is undefined.");
  }
  const ruleRegExp = transformRoutingRuleToRegExp(routingRule);
  return pathname.match(ruleRegExp) !== null;
}
__name(isRoutingRuleMatch, "isRoutingRuleMatch");
function transformRoutingRuleToRegExp(rule) {
  let transformedRule;
  if (rule === "/" || rule === "/*") {
    transformedRule = rule;
  } else if (rule.endsWith("/*")) {
    transformedRule = `${rule.substring(0, rule.length - 2)}(/*)?`;
  } else if (rule.endsWith("/")) {
    transformedRule = `${rule.substring(0, rule.length - 1)}(/)?`;
  } else if (rule.endsWith("*")) {
    transformedRule = rule;
  } else {
    transformedRule = `${rule}(/)?`;
  }
  transformedRule = `^${transformedRule.replaceAll(/\./g, "\\.").replaceAll(/\*/g, ".*")}$`;
  return new RegExp(transformedRule);
}
__name(transformRoutingRuleToRegExp, "transformRoutingRuleToRegExp");

// .wrangler/tmp/pages-Y1G9U5/d781zz4i7bj.js
var define_ROUTES_default = {
  version: 1,
  include: ["/api/*"],
  exclude: []
};
var routes2 = define_ROUTES_default;
var pages_dev_pipeline_default = {
  fetch(request, env, context) {
    const { pathname } = new URL(request.url);
    for (const exclude of routes2.exclude) {
      if (isRoutingRuleMatch(pathname, exclude)) {
        return env.ASSETS.fetch(request);
      }
    }
    for (const include of routes2.include) {
      if (isRoutingRuleMatch(pathname, include)) {
        const workerAsHandler = middleware_loader_entry_default;
        if (workerAsHandler.fetch === void 0) {
          throw new TypeError("Entry point missing `fetch` handler");
        }
        return workerAsHandler.fetch(request, env, context);
      }
    }
    return env.ASSETS.fetch(request);
  }
};

// ../../../../../../../../../root/.nvm/versions/node/v22.23.1/lib/node_modules/wrangler/templates/middleware/middleware-ensure-req-body-drained.ts
var drainBody2 = /* @__PURE__ */ __name(async (request, env, _ctx, middlewareCtx) => {
  try {
    return await middlewareCtx.next(request, env);
  } finally {
    try {
      if (request.body !== null && !request.bodyUsed) {
        const reader = request.body.getReader();
        while (!(await reader.read()).done) {
        }
      }
    } catch (e) {
      console.error("Failed to drain the unused request body.", e);
    }
  }
}, "drainBody");
var middleware_ensure_req_body_drained_default2 = drainBody2;

// ../../../../../../../../../root/.nvm/versions/node/v22.23.1/lib/node_modules/wrangler/templates/middleware/middleware-miniflare3-json-error.ts
function reduceError2(e) {
  return {
    name: e?.name,
    message: e?.message ?? String(e),
    stack: e?.stack,
    cause: e?.cause === void 0 ? void 0 : reduceError2(e.cause)
  };
}
__name(reduceError2, "reduceError");
var jsonError2 = /* @__PURE__ */ __name(async (request, env, _ctx, middlewareCtx) => {
  try {
    return await middlewareCtx.next(request, env);
  } catch (e) {
    const error = reduceError2(e);
    const body = JSON.stringify(error);
    const headers = {
      "Content-Type": "application/json",
      "MF-Experimental-Error-Stack": "true"
    };
    const encoded = encodeURIComponent(body);
    if (encoded.length <= 8192) {
      headers["MF-Experimental-Error-Stack-Payload"] = encoded;
    }
    return new Response(body, { status: 500, headers });
  }
}, "jsonError");
var middleware_miniflare3_json_error_default2 = jsonError2;

// .wrangler/tmp/bundle-g7rM3r/middleware-insertion-facade.js
var __INTERNAL_WRANGLER_MIDDLEWARE__2 = [
  middleware_ensure_req_body_drained_default2,
  middleware_miniflare3_json_error_default2
];
var middleware_insertion_facade_default2 = pages_dev_pipeline_default;

// ../../../../../../../../../root/.nvm/versions/node/v22.23.1/lib/node_modules/wrangler/templates/middleware/common.ts
var __facade_middleware__2 = [];
function __facade_register__2(...args) {
  __facade_middleware__2.push(...args.flat());
}
__name(__facade_register__2, "__facade_register__");
function __facade_invokeChain__2(request, env, ctx, dispatch, middlewareChain) {
  const [head, ...tail] = middlewareChain;
  const middlewareCtx = {
    dispatch,
    next(newRequest, newEnv) {
      return __facade_invokeChain__2(newRequest, newEnv, ctx, dispatch, tail);
    }
  };
  return head(request, env, ctx, middlewareCtx);
}
__name(__facade_invokeChain__2, "__facade_invokeChain__");
function __facade_invoke__2(request, env, ctx, dispatch, finalMiddleware) {
  return __facade_invokeChain__2(request, env, ctx, dispatch, [
    ...__facade_middleware__2,
    finalMiddleware
  ]);
}
__name(__facade_invoke__2, "__facade_invoke__");

// .wrangler/tmp/bundle-g7rM3r/middleware-loader.entry.ts
var __Facade_ScheduledController__2 = class ___Facade_ScheduledController__2 {
  constructor(scheduledTime, cron, noRetry) {
    this.scheduledTime = scheduledTime;
    this.cron = cron;
    this.#noRetry = noRetry;
  }
  scheduledTime;
  cron;
  static {
    __name(this, "__Facade_ScheduledController__");
  }
  #noRetry;
  noRetry() {
    if (!(this instanceof ___Facade_ScheduledController__2)) {
      throw new TypeError("Illegal invocation");
    }
    this.#noRetry();
  }
};
function wrapExportedHandler2(worker) {
  if (__INTERNAL_WRANGLER_MIDDLEWARE__2 === void 0 || __INTERNAL_WRANGLER_MIDDLEWARE__2.length === 0) {
    return worker;
  }
  for (const middleware of __INTERNAL_WRANGLER_MIDDLEWARE__2) {
    __facade_register__2(middleware);
  }
  const fetchDispatcher = /* @__PURE__ */ __name(function(request, env, ctx) {
    if (worker.fetch === void 0) {
      throw new Error("Handler does not export a fetch() function.");
    }
    return worker.fetch(request, env, ctx);
  }, "fetchDispatcher");
  return {
    ...worker,
    fetch(request, env, ctx) {
      const dispatcher = /* @__PURE__ */ __name(function(type, init) {
        if (type === "scheduled" && worker.scheduled !== void 0) {
          const controller = new __Facade_ScheduledController__2(
            Date.now(),
            init.cron ?? "",
            () => {
            }
          );
          return worker.scheduled(controller, env, ctx);
        }
      }, "dispatcher");
      return __facade_invoke__2(request, env, ctx, dispatcher, fetchDispatcher);
    }
  };
}
__name(wrapExportedHandler2, "wrapExportedHandler");
function wrapWorkerEntrypoint2(klass) {
  if (__INTERNAL_WRANGLER_MIDDLEWARE__2 === void 0 || __INTERNAL_WRANGLER_MIDDLEWARE__2.length === 0) {
    return klass;
  }
  for (const middleware of __INTERNAL_WRANGLER_MIDDLEWARE__2) {
    __facade_register__2(middleware);
  }
  return class extends klass {
    #fetchDispatcher = /* @__PURE__ */ __name((request, env, ctx) => {
      this.env = env;
      this.ctx = ctx;
      if (super.fetch === void 0) {
        throw new Error("Entrypoint class does not define a fetch() function.");
      }
      return super.fetch(request);
    }, "#fetchDispatcher");
    #dispatcher = /* @__PURE__ */ __name((type, init) => {
      if (type === "scheduled" && super.scheduled !== void 0) {
        const controller = new __Facade_ScheduledController__2(
          Date.now(),
          init.cron ?? "",
          () => {
          }
        );
        return super.scheduled(controller);
      }
    }, "#dispatcher");
    fetch(request) {
      return __facade_invoke__2(
        request,
        this.env,
        this.ctx,
        this.#dispatcher,
        this.#fetchDispatcher
      );
    }
  };
}
__name(wrapWorkerEntrypoint2, "wrapWorkerEntrypoint");
var WRAPPED_ENTRY2;
if (typeof middleware_insertion_facade_default2 === "object") {
  WRAPPED_ENTRY2 = wrapExportedHandler2(middleware_insertion_facade_default2);
} else if (typeof middleware_insertion_facade_default2 === "function") {
  WRAPPED_ENTRY2 = wrapWorkerEntrypoint2(middleware_insertion_facade_default2);
}
var middleware_loader_entry_default2 = WRAPPED_ENTRY2;
export {
  __INTERNAL_WRANGLER_MIDDLEWARE__2 as __INTERNAL_WRANGLER_MIDDLEWARE__,
  middleware_loader_entry_default2 as default
};
//# sourceMappingURL=d781zz4i7bj.js.map
