import { SCHEMA_VERSION } from "./business-fact-merger.js";

const BASE_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer"
};
export function safeError(code, message, diagnosticCode) {
  const error = { code, message };
  if (diagnosticCode) error.diagnosticCode = diagnosticCode;
  return error;
}
export function jsonResponse(payload, { status = 200, head = false, headers = {} } = {}) {
  const allHeaders = { ...BASE_HEADERS, ...headers };
  const dc = payload?.error?.diagnosticCode;
  if (dc) allHeaders["X-Portfolio-Diagnostic-Code"] = String(dc);
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
