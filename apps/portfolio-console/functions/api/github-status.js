/*  api/github-status.js  —  Phase 2A handler (PR #193 extended)
 *
 *  Preserved contracts:
 *    - GET and HEAD only
 *    - fixed repository allowlist (no arbitrary query)
 *    - server-side only
 *    - static fallback when credentials absent
 *    - CSP connect-src self
 *    - no raw upstream error reflection
 *    - no secret leakage
 *
 *  Configuration-missing response (safe fallback without credentials):
 *    - { ok: false, schemaVersion: 2, businesses: [], error: { code: "CONFIGURATION_MISSING" } }
 */

import { InstallationTokenProvider } from "../_lib/github-app-auth.js";
import { GitHubClient } from "../_lib/github-client.js";
import { RuntimeSnapshotCache } from "../_lib/cache.js";
import { createGitHubStatusService } from "../_lib/github-status-service.js";
import { configurationMissingPayload, cacheConfigurationMissingPayload, jsonResponse, safeError, validDiagnosticCode } from "../_lib/response.js";
import { bindFetchImpl } from "../_lib/runtime-fetch.js";
import { OUTBOUND_DEADLINES, OutboundTimeoutError, createDeadlineRunner, createStageLogger } from "../_lib/outbound-deadline.js";
import { SCHEMA_VERSION } from "../_lib/business-fact-merger.js";
import { buildIdentitySource } from "../../business-identity-data.js";

const REQUIRED_BINDINGS = ["GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID", "GITHUB_APP_PRIVATE_KEY_PKCS8"];

function hasConfiguration(env) {
  return REQUIRED_BINDINGS.every((name) => typeof env?.[name] === "string" && env[name].trim());
}

function hasSnapshotCache(env) {
  return Boolean(env?.GITHUB_STATUS_SNAPSHOT_KV?.get && env?.GITHUB_STATUS_SNAPSHOT_KV?.put);
}

function failure(code, message, diagnosticCode) {
  return { ok: false, schemaVersion: SCHEMA_VERSION, syncedAt: null, stale: false, error: safeError(code, message, diagnosticCode), businesses: [] };
}

export async function handleGitHubStatusRequest({
  request,
  env = {},
  fetchImpl = fetch,
  cache,
  now = () => Date.now(),
  cryptoImpl = globalThis.crypto,
  client: injectedClient = null,
  timeouts = OUTBOUND_DEADLINES,
  timers,
  AbortControllerImpl = AbortController,
  stageLogger,
  registerBackgroundTask = () => {},
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

  const logStage = stageLogger || createStageLogger(undefined, now);
  const deadlines = createDeadlineRunner(timers);

  try {
    const boundFetch = bindFetchImpl(fetchImpl);
    const authProvider = injectedClient
      ? null
      : new InstallationTokenProvider({
          appId: env.GITHUB_APP_ID,
          installationId: env.GITHUB_APP_INSTALLATION_ID,
          privateKeyPkcs8: env.GITHUB_APP_PRIVATE_KEY_PKCS8,
          fetchImpl: boundFetch,
          now,
          cryptoImpl,
          timeouts,
          timers,
          AbortControllerImpl,
          stageLogger: logStage,
        });
    const client = injectedClient || new GitHubClient({ authProvider, fetchImpl: boundFetch, timeouts, timers, AbortControllerImpl, stageLogger: logStage });
    const snapshotCache = cache || new RuntimeSnapshotCache({ kv: env.GITHUB_STATUS_SNAPSHOT_KV, now });
    const identitySource = buildIdentitySource();
    const service = createGitHubStatusService({ client, cache: snapshotCache, now, identitySource, timeouts, timers, registerBackgroundTask });
    const result = await deadlines.runWithDeadline(service.getStatus(), timeouts.handlerBackstopMs, "handler");
    const headers = { "X-Portfolio-Cache": result.cacheState };
    if (result.cacheState === "stale" && result.payload.errors?.length) {
      const lastErr = [...result.payload.errors].reverse().find((e) => e.diagnosticCode);
      if (lastErr) {
        const validated = validDiagnosticCode(lastErr.diagnosticCode);
        if (validated) headers["X-Portfolio-Diagnostic-Code"] = validated;
      }
    }
    return jsonResponse(result.payload, {
      status: result.status,
      head: isHead,
      headers,
    });
  } catch (error) {
    if (error instanceof OutboundTimeoutError) {
      return jsonResponse(failure("UPSTREAM_UNAVAILABLE", "GitHub synchronization exceeded its time budget.", "GITHUB_GRAPHQL_TIMEOUT"), { status: 504, head: isHead });
    }
    return jsonResponse(failure("INTERNAL_ERROR", "GitHub live synchronization could not be completed.", "UNKNOWN_INTERNAL"), { status: 500, head: isHead });
  }
}

export async function onRequest(context) {
  // Register timed-out stale refreshes with the Pages runtime so they survive the
  // response. The arrow keeps `context` as the receiver (no destructured binding)
  // and is a safe no-op if this runtime exposes no waitUntil. (Issue #345, Defect B.)
  return handleGitHubStatusRequest({
    request: context.request,
    env: context.env,
    registerBackgroundTask: (promise) => { if (typeof context.waitUntil === "function") context.waitUntil(promise); },
  });
}
