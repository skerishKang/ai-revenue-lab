import { currentBaseUrl } from './baseUrl';
import { sessionCookieHeader } from '../auth/session';

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly detail?: string;

  constructor(status: number, code: string, message: string, detail?: string) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.detail = detail;
  }

  get isUnauthorized(): boolean {
    return this.status === 401;
  }
}

export interface ApiRequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  /** JSON-serializable request body. */
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Absolute URL instead of a path relative to the API origin. */
  absoluteUrl?: string;
  /** Skip the session cookie (used by the sign-in endpoints). */
  anonymous?: boolean;
}

function isAbort(error: unknown): boolean {
  return (
    typeof error === 'object' &&
    error !== null &&
    (error as { name?: string }).name === 'AbortError'
  );
}

export function isAbortError(error: unknown): boolean {
  return isAbort(error);
}

/**
 * One native HTTP call against the existing PADIEM server.
 *
 * The session cookie is replayed as a `Cookie` header so the server resolves
 * the very same signed session a browser would resolve. No new credential,
 * no new identity authority, no client-side tier or model decision.
 */
export async function apiRequest<T = unknown>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const {
    method = 'GET',
    body,
    headers = {},
    signal,
    absoluteUrl,
    anonymous = false,
  } = options;

  const url = absoluteUrl ?? `${currentBaseUrl()}${path}`;
  const requestHeaders: Record<string, string> = {
    Accept: 'application/json',
    ...headers,
  };

  if (!anonymous) {
    const cookie = await sessionCookieHeader();
    if (cookie) {
      requestHeaders.Cookie = cookie;
    }
  }

  let payload: string | undefined;
  if (body !== undefined) {
    requestHeaders['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: requestHeaders,
      body: payload,
      signal,
    });
  } catch (error) {
    if (isAbort(error)) {
      throw error;
    }
    throw new ApiError(
      0,
      'network_unreachable',
      'PADIEM 서버에 연결할 수 없습니다. 네트워크를 확인해 주세요.',
    );
  }

  const text = await response.text();
  let data: unknown = null;
  if (text.length > 0) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const body = data as { error?: { code?: string; message?: string; detail?: string } } | null;
    throw new ApiError(
      response.status,
      body?.error?.code ?? `http_${response.status}`,
      body?.error?.message ?? '요청을 처리하지 못했습니다. 다시 시도해 주세요.',
      body?.error?.detail,
    );
  }

  return data as T;
}

/** Raw variant that hands back the untouched `Response` (cookie capture). */
export async function apiRequestRaw(
  path: string,
  options: ApiRequestOptions = {},
): Promise<Response> {
  const {method = 'GET', body, headers = {}, signal, absoluteUrl, anonymous = false} = options;
  const url = absoluteUrl ?? `${currentBaseUrl()}${path}`;
  const requestHeaders: Record<string, string> = {Accept: 'application/json', ...headers};

  if (!anonymous) {
    const cookie = await sessionCookieHeader();
    if (cookie) {
      requestHeaders.Cookie = cookie;
    }
  }

  let payload: string | undefined;
  if (body !== undefined) {
    requestHeaders['Content-Type'] = 'application/json';
    payload = JSON.stringify(body);
  }

  return fetch(url, {method, headers: requestHeaders, body: payload, signal});
}
