import { InstallationTokenProvider } from "../_lib/github-app-auth.js";
import { GitHubClient } from "../_lib/github-client.js";
import { RuntimeSnapshotCache } from "../_lib/cache.js";
import { createGitHubStatusService } from "../_lib/github-status-service.js";
import { configurationMissingPayload, jsonResponse, safeError } from "../_lib/response.js";

const REQUIRED_BINDINGS = [
  "GITHUB_APP_ID",
  "GITHUB_APP_INSTALLATION_ID",
  "GITHUB_APP_PRIVATE_KEY_PKCS8"
];

function hasConfiguration(env) {
  return REQUIRED_BINDINGS.every((name) => typeof env?.[name] === "string" && env[name].trim());
}

export async function handleGitHubStatusRequest({
  request,
  env = {},
  fetchImpl = fetch,
  cache,
  now = () => Date.now(),
  cryptoImpl = globalThis.crypto,
  client: injectedClient = null
}) {
  const method = String(request.method || "GET").toUpperCase();
  const isHead = method === "HEAD";
  if (method !== "GET" && !isHead) {
    return jsonResponse(
      {
        ok: false,
        schemaVersion: 1,
        syncedAt: null,
        stale: false,
        error: safeError("METHOD_NOT_ALLOWED", "Only GET and HEAD are supported."),
        businesses: []
      },
      { status: 405, headers: { Allow: "GET, HEAD" } }
    );
  }

  const url = new URL(request.url);
  if ([...url.searchParams.keys()].length > 0) {
    return jsonResponse(
      {
        ok: false,
        schemaVersion: 1,
        syncedAt: null,
        stale: false,
        error: safeError("INVALID_QUERY", "Query parameters are not supported."),
        businesses: []
      },
      { status: 400, head: isHead }
    );
  }

  if (!hasConfiguration(env)) {
    return jsonResponse(configurationMissingPayload(), { status: 503, head: isHead });
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
    const snapshotCache = cache || new RuntimeSnapshotCache({ now });
    const service = createGitHubStatusService({ client, cache: snapshotCache, now });
    const result = await service.getStatus();
    return jsonResponse(result.payload, {
      status: result.status,
      head: isHead,
      headers: { "X-Portfolio-Cache": result.cacheState }
    });
  } catch {
    return jsonResponse(
      {
        ok: false,
        schemaVersion: 1,
        syncedAt: null,
        stale: false,
        error: safeError("INTERNAL_ERROR", "GitHub live synchronization could not be completed."),
        businesses: []
      },
      { status: 500, head: isHead }
    );
  }
}

export async function onRequest(context) {
  return handleGitHubStatusRequest({ request: context.request, env: context.env });
}
