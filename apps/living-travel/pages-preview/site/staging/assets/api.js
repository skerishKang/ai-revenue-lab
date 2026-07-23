// Living Travel — Staging API client.
//
// Calls the isolated Modal staging API at API_BASE + API_PREFIX. Every request
// carries a fresh Firebase ID token as a Bearer credential. The token is
// obtained on demand from the Firebase SDK and is never stored in custom
// localStorage/sessionStorage by this app.
import { API_BASE, API_PREFIX } from "./config.js";
import { getCurrentIdToken } from "./firebase.js";

export class ApiError extends Error {
  constructor(status, detail) {
    super(`api_error_${status}`);
    this.status = status;
    this.detail = detail;
  }
}

async function request(method, path, body) {
  const token = await getCurrentIdToken();
  if (!token) {
    throw new ApiError(401, "not_authenticated");
  }
  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: "application/json",
  };
  const options = { method, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(`${API_BASE}${API_PREFIX}${path}`, options);
  let payload = null;
  const text = await response.text();
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }
  if (!response.ok) {
    const detail = payload && typeof payload === "object" ? payload.detail : null;
    throw new ApiError(response.status, detail ?? `http_${response.status}`);
  }
  return payload;
}

export const api = {
  get: (path) => request("GET", path),
  post: (path, body) => request("POST", path, body ?? {}),
  put: (path, body) => request("PUT", path, body ?? {}),
};

// Human-readable message for an ApiError, safe to render via textContent.
export function describeError(err) {
  if (err instanceof ApiError) {
    if (err.status === 401) return "인증이 필요합니다. 다시 로그인하세요.";
    if (err.status === 403) return "접근 권한이 없습니다.";
    if (err.status === 404) return "요청한 항목을 찾을 수 없습니다.";
    if (err.status === 409) {
      const detail = err.detail;
      const category =
        detail && typeof detail === "object" ? detail.category : detail;
      return `처리할 수 없습니다 (${category || "conflict"}).`;
    }
    return `요청 실패 (status ${err.status}).`;
  }
  return "네트워크 오류가 발생했습니다.";
}
