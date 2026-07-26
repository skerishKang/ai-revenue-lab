import { InstallationTokenProvider } from "../_lib/github-app-auth.js";
import { GitHubClient } from "../_lib/github-client.js";
import { RuntimeSnapshotCache } from "../_lib/cache.js";
import { createGitHubStatusService } from "../_lib/github-status-service.js";
import { cacheConfigurationMissingPayload, configurationMissingPayload, jsonResponse, safeError } from "../_lib/response.js";

const REQUIRED_BINDINGS = ["GITHUB_APP_ID", "GITHUB_APP_INSTALLATION_ID", "GITHUB_APP_PRIVATE_KEY_PKCS8"];
function hasConfiguration(env) { return REQUIRED_BINDINGS.every((name) => typeof env?.[name] === "string" && env[name].trim()); }
function hasSnapshotCache(env) { return Boolean(env?.GITHUB_STATUS_SNAPSHOT_KV?.get && env?.GITHUB_STATUS_SNAPSHOT_KV?.put); }
function failure(code, message) { return { ok: false, schemaVersion: 1, syncedAt: null, stale: false, error: safeError(code, message), businesses: [] }; }

export async function handleGitHubStatusRequest({ request, env = {}, fetchImpl = fetch, cache, now = () => Date.now(),
  cryptoImpl = globalThis.crypto, client: injectedClient = null }) {
  const method = String(request.method || "GET").toUpperCase();
  const isHead = method === "HEAD";
  if (method !== "GET" && !isHead) return jsonResponse(failure("METHOD_NOT_ALLOWED", "Only GET and HEAD are supported."),
    { status: 405, headers: { Allow: "GET, HEAD" } });
  const url = new URL(request.url);
  if ([...url.searchParams.keys()].length > 0) return jsonResponse(failure("INVALID_QUERY", "Query parameters are not supported."), { status: 400, head: isHead });
  if (!hasConfiguration(env)) return jsonResponse(configurationMissingPayload(), { status: 503, head: isHead });
  if (!cache && !hasSnapshotCache(env)) return jsonResponse(cacheConfigurationMissingPayload(), { status: 503, head: isHead });
  try {
    const authProvider = injectedClient ? null : new InstallationTokenProvider({ appId: env.GITHUB_APP_ID,
      installationId: env.GITHUB_APP_INSTALLATION_ID, privateKeyPkcs8: env.GITHUB_APP_PRIVATE_KEY_PKCS8,
      fetchImpl, now, cryptoImpl });
    const client = injectedClient || new GitHubClient({ authProvider, fetchImpl });
    const snapshotCache = cache || new RuntimeSnapshotCache({ kv: env.GITHUB_STATUS_SNAPSHOT_KV, now });
    const result = await createGitHubStatusService({ client, cache: snapshotCache, now }).getStatus();
    return jsonResponse(result.payload, { status: result.status, head: isHead, headers: { "X-Portfolio-Cache": result.cacheState } });
  } catch {
    return jsonResponse(failure("INTERNAL_ERROR", "GitHub live synchronization could not be completed."), { status: 500, head: isHead });
  }
}
export async function onRequest(context) { return handleGitHubStatusRequest({ request: context.request, env: context.env }); }
