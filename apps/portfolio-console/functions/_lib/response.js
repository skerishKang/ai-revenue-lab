const BASE_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Cache-Control": "no-store",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer"
};
export function safeError(code, message) { return { code, message }; }
export function jsonResponse(payload, { status = 200, head = false, headers = {} } = {}) {
  return new Response(head ? null : JSON.stringify(payload), { status, headers: { ...BASE_HEADERS, ...headers } });
}
export function configurationMissingPayload() {
  return { ok: false, schemaVersion: 1, syncedAt: null, stale: false,
    error: safeError("CONFIGURATION_MISSING", "GitHub live synchronization is not configured."), businesses: [] };
}
export function cacheConfigurationMissingPayload() {
  return { ok: false, schemaVersion: 1, syncedAt: null, stale: false,
    error: safeError("CACHE_CONFIGURATION_MISSING", "GitHub live synchronization cache is not configured."), businesses: [] };
}
