import AsyncStorage from '@react-native-async-storage/async-storage';

import { SESSION_COOKIE_NAME } from '../api/config';

const SESSION_KEY = 'padiem.session.cookie';

let cachedCookie: string | null = null;
let hydrated = false;

/**
 * Read the value of the `padiem_session` cookie from a `Set-Cookie` header.
 *
 * The existing server issues the session as an httpOnly cookie. A native HTTP
 * client has no browser cookie jar, so the app keeps the cookie VALUE and
 * replays it as a `Cookie` request header. The credential itself, its
 * signature and its server-side authority are unchanged.
 */
export function extractSessionCookie(headers: {
  get(name: string): string | null;
}): string | null {
  const raw = headers.get('set-cookie');
  if (!raw) {
    return null;
  }
  const match = new RegExp(`${SESSION_COOKIE_NAME}=([^;,]+)`).exec(raw);
  return match ? match[1] : null;
}

/** Build a `Cookie` header value from every `Set-Cookie` header line. */
export function collectSetCookieHeaders(headers: {
  get(name: string): string | null;
}): string[] {
  const single = headers.get('set-cookie');
  if (!single) {
    return [];
  }
  return single
    .split(/,(?=\s*[A-Za-z0-9_.-]+=)/)
    .map(part => part.trim())
    .filter(Boolean);
}

export async function loadSessionCookie(): Promise<string | null> {
  if (hydrated) {
    return cachedCookie;
  }
  const stored = await AsyncStorage.getItem(SESSION_KEY);
  cachedCookie = stored && stored.length > 0 ? stored : null;
  hydrated = true;
  return cachedCookie;
}

export async function setSessionCookie(value: string): Promise<void> {
  cachedCookie = value;
  hydrated = true;
  await AsyncStorage.setItem(SESSION_KEY, value);
}

export async function clearSessionCookie(): Promise<void> {
  cachedCookie = null;
  hydrated = true;
  await AsyncStorage.removeItem(SESSION_KEY);
}

/** `Cookie` header value for the current session, or `null` when signed out. */
export async function sessionCookieHeader(): Promise<string | null> {
  const cookie = await loadSessionCookie();
  if (!cookie) {
    return null;
  }
  return `${SESSION_COOKIE_NAME}=${cookie}`;
}
