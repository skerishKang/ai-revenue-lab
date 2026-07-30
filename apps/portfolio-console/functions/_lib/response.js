import { SCHEMA_VERSION } from "./business-fact-merger.js";

const BASE_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Portfolio-Function-Contract": "github-status-diagnostics-v1"
};

const ALLOWED_DIAGNOSTIC_CODES = Object.freeze([
  "CONFIGURATION_MISSING",
  "CACHE_CONFIGURATION_MISSING",
  "CRYPTO_UNAVAILABLE",
  "PRIVATE_KEY_INVALID",
  "JWT_SIGNING_FAILED",
  "INSTALLATION_TOKEN_EXCHANGE_FAILED",
  "INSTALLATION_TOKEN_RESPONSE_INVALID",
  "GITHUB_GRAPHQL_AUTH_FAILED",
  "GITHUB_GRAPHQL_RATE_LIMITED",
  "GITHUB_GRAPHQL_REQUEST_FAILED",
  "GITHUB_GRAPHQL_RESPONSE_INVALID",
  "GITHUB_GRAPHQL_DATA_UNAVAILABLE",
  "CACHE_READ_FAILED",
  "UNKNOWN_INTERNAL",
]);

const DIAGNOSTIC_SET = new Set(ALLOWED_DIAGNOSTIC_CODES);

export function validDiagnosticCode(code) {
  if (typeof code === "string" && DIAGNOSTIC_SET.has(code)) return code;
  return "UNKNOWN_INTERNAL";
}

export function safeError(code, message, diagnosticCode) {
  const error = { code, message };
  const dc = diagnosticCode ? validDiagnosticCode(diagnosticCode) : null;
  if (dc) error.diagnosticCode = dc;
  return error;
}
export function jsonResponse(payload, { status = 200, head = false, headers = {} } = {}) {
  const allHeaders = { ...BASE_HEADERS, ...headers };
  const dc = payload?.error?.diagnosticCode;
  if (typeof dc === "string" && DIAGNOSTIC_SET.has(dc)) allHeaders["X-Portfolio-Diagnostic-Code"] = dc;
  return new Response(head ? null : JSON.stringify(payload), { status, headers: allHeaders });
}
export function configurationMissingPayload() {
  return { ok: false, schemaVersion: SCHEMA_VERSION, syncedAt: null, stale: false,
    error: safeError("CONFIGURATION_MISSING", "GitHub live synchronization is not configured.", "CONFIGURATION_MISSING"), businesses: [] };
}
export function cacheConfigurationMissingPayload() {
  return { ok: false, schemaVersion: SCHEMA_VERSION, syncedAt: null, stale: false,
    error: safeError("CACHE_CONFIGURATION_MISSING", "GitHub live synchronization cache is not configured.", "CACHE_CONFIGURATION_MISSING"), businesses: [] };
}
