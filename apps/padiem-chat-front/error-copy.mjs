/**
 * The front door's user-facing copy, in one file.
 *
 * Until now a failed upstream call answered every request — including a
 * browser navigation — with a JSON body, so a half-finished login painted
 * `{"error":{"code":"upstream_timeout",…}}` as the page (the shape
 * test/auth_callback_timeout.test.mjs describes but never sent as a browser).
 * A navigation now gets a Korean sentence and one way back in; a machine call
 * keeps exactly the JSON it already parses.
 *
 * `Accept: text/html` is the only signal used, so a request that does not name
 * HTML — fetch(), curl, a test double — is unaffected.
 */

export const ERROR_COPY = Object.freeze({
  upstream_timeout: Object.freeze({
    title: "응답이 너무 오래 걸려서 멈췄어요",
    body: "서버가 제 시간에 답하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  }),
  upstream_transport_failed: Object.freeze({
    title: "서버와 연결하지 못했어요",
    body: "네트워크 상태를 확인한 뒤 다시 시도해 주세요.",
  }),
  service_unavailable: Object.freeze({
    title: "잠시 점검 중입니다",
    body: "곧 다시 이용할 수 있습니다. 잠시 후 새로고침해 주세요.",
  }),
});

export const DEFAULT_ERROR_COPY = Object.freeze({
  title: "요청을 처리하지 못했어요",
  body: "잠시 후 다시 시도해 주세요.",
});

export function copyFor(code) {
  const known = Object.prototype.hasOwnProperty.call(ERROR_COPY, code) ? ERROR_COPY[code] : null;
  return known || DEFAULT_ERROR_COPY;
}

export function wantsHtml(request) {
  return /text\/html/i.test(String(request?.headers?.get("accept") || ""));
}

// Only the path is echoed back as a link, never the query: the login callback
// carries state and code there, and a page is not where those belong. A failed
// login has nothing to retry on its own, so it goes back to the front page.
export function retryHref(pathname) {
  return typeof pathname === "string" && pathname.startsWith("/auth/") ? "/" : (pathname || "/");
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

export function errorPageHtml(code, pathname) {
  const copy = copyFor(code);
  const href = escapeHtml(retryHref(pathname));
  return `<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>${escapeHtml(copy.title)}</title>
<style>body{font-family:system-ui,sans-serif;margin:0;display:grid;place-items:center;min-height:100vh;background:#0f1115;color:#e8eaf0}main{text-align:center;padding:24px;max-width:32em}h1{font-size:1.25rem;font-weight:600;margin:0 0 8px}p{color:#9aa3b2;margin:0 0 20px;line-height:1.6}a{display:inline-block;padding:12px 20px;border-radius:10px;background:#79bce7;color:#10202e;font-weight:650;text-decoration:none}@media (prefers-color-scheme:light){body{background:#f2f5f7;color:#17202a}p{color:#53606c}}</style>
</head><body><main><h1>${escapeHtml(copy.title)}</h1><p>${escapeHtml(copy.body)}</p><a href="${href}">다시 시도</a></main></body></html>`;
}
