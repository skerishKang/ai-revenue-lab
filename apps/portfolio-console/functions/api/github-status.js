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
import { configurationMissingPayload, cacheConfigurationMissingPayload, jsonResponse, safeError } from "../_lib/response.js";
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
    const authProvider = injectedClient
      ? null
      : new InstallationTokenProvider({
          appId: env.GITHUB_APP_ID,
          installationId: env.GITHUB_APP_INSTALLATION_ID,
          privateKeyPkcs8: env.GITHUB_APP_PRIVATE_KEY_PKCS8,
          fetchImpl,
          now,
          cryptoImpl,
        });
    const client = injectedClient || new GitHubClient({ authProvider, fetchImpl });
    const snapshotCache = cache || new RuntimeSnapshotCache({ kv: env.GITHUB_STATUS_SNAPSHOT_KV, now });
    const identitySource = buildIdentitySource();
    const result = await createGitHubStatusService({ client, cache: snapshotCache, now, identitySource }).getStatus();
    const headers = { "X-Portfolio-Cache": result.cacheState };
    if (result.cacheState === "stale" && result.payload.errors?.length) {
      const lastDiagnostic = [...result.payload.errors].reverse().find((e) => e.diagnosticCode);
      if (lastDiagnostic) headers["X-Portfolio-Diagnostic-Code"] = lastDiagnostic.diagnosticCode;
    }
    return jsonResponse(result.payload, {
      status: result.status,
      head: isHead,
      headers,
    });
  } catch {
    return jsonResponse(failure("INTERNAL_ERROR", "GitHub live synchronization could not be completed.", "UNKNOWN_INTERNAL"), { status: 500, head: isHead });
  }
}

export async function onRequest(context) {
  return handleGitHubStatusRequest({ request: context.request, env: context.env });
}
