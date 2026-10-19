/**
 * #3611 — host-side public-URL policy mirror.
 *
 * The canonical Padiem public-URL contract is the Python policy
 * (`packages/padiem-ai-core/padiem_ai_core/web_runtime.py:normalize_public_url`).
 * The Desktop host cannot import Python, so this module mirrors the *decision*
 * function and is deliberately never weaker:
 *
 *   - it refuses every IP-literal host, including global IPv4/IPv6 literals the
 *     canonical literal-host policy accepts;
 *   - it refuses anything the WHATWG URL parser refuses (e.g. a space in the host),
 *     which the canonical policy currently accepts;
 *   - it refuses localhost / metadata / internal-suffix hosts, userinfo, non-http(s)
 *     schemes, control characters, over-length input and out-of-range ports.
 *
 * The host never navigates a caller-supplied raw string: it navigates the
 * canonical normalized URL that the Python policy produced, and requires this
 * module to accept it. Both implementations are pinned by the shared vectors in
 * `tests/vectors/public-url-policy-vectors.json`, whose parity invariant is
 * "host-allowed ⊆ canonical-allowed".
 */

export const MAX_PUBLIC_URL_CHARS = 2048;

export const BLOCKED_HOST_SUFFIXES = [
  '.localhost',
  '.local',
  '.internal',
  '.lan',
  '.home',
] as const;

export const BLOCKED_EXACT_HOSTS = [
  'localhost',
  'localhost.localdomain',
  'metadata.google.internal',
] as const;

export type PublicUrlRejection =
  | 'not_a_string'
  | 'empty'
  | 'too_long'
  | 'control_characters'
  | 'malformed'
  | 'scheme'
  | 'userinfo'
  | 'host_missing'
  | 'ip_literal_host'
  | 'blocked_host'
  | 'port';

export type PublicUrlEvaluation =
  | { readonly allowed: true }
  | { readonly allowed: false; readonly reason: PublicUrlRejection };

const ALLOWED_SCHEMES = new Set(['http:', 'https:']);

/** True when the host is an IPv4/IPv6 literal (bracketed or bare). */
export function isIpLiteralHost(hostname: string): boolean {
  const bare =
    hostname.startsWith('[') && hostname.endsWith(']') ? hostname.slice(1, -1) : hostname;
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(bare)) return true;
  if (/^\d+(\.\d+)*$/.test(bare)) return true;
  return bare.includes(':') && /^[0-9a-fA-F:.]+$/.test(bare);
}

function evaluateParts(value: unknown): PublicUrlEvaluation {
  if (typeof value !== 'string') return { allowed: false, reason: 'not_a_string' };
  const raw = value.trim();
  if (!raw) return { allowed: false, reason: 'empty' };
  if (raw.length > MAX_PUBLIC_URL_CHARS) return { allowed: false, reason: 'too_long' };
  for (const character of raw) {
    if (character.codePointAt(0)! < 32) {
      return { allowed: false, reason: 'control_characters' };
    }
  }

  let parsed: URL;
  try {
    parsed = new URL(raw);
  } catch {
    return { allowed: false, reason: 'malformed' };
  }

  if (!ALLOWED_SCHEMES.has(parsed.protocol.toLowerCase())) {
    return { allowed: false, reason: 'scheme' };
  }
  if (parsed.username !== '' || parsed.password !== '') {
    return { allowed: false, reason: 'userinfo' };
  }

  const hostname = parsed.hostname.toLowerCase();
  if (!hostname) return { allowed: false, reason: 'host_missing' };
  if (isIpLiteralHost(hostname)) return { allowed: false, reason: 'ip_literal_host' };
  if ((BLOCKED_EXACT_HOSTS as readonly string[]).includes(hostname)) {
    return { allowed: false, reason: 'blocked_host' };
  }
  if (BLOCKED_HOST_SUFFIXES.some((suffix) => hostname.endsWith(suffix))) {
    return { allowed: false, reason: 'blocked_host' };
  }

  const port = parsed.port === '' ? null : Number(parsed.port);
  if (port !== null && (!Number.isInteger(port) || port < 1 || port > 65535)) {
    return { allowed: false, reason: 'port' };
  }

  return { allowed: true };
}

export function evaluatePublicUrl(value: unknown): PublicUrlEvaluation {
  return evaluateParts(value);
}

export function isPermittedPublicUrl(value: unknown): boolean {
  return evaluateParts(value).allowed;
}

/** `scheme://host[:port]` with the default port omitted, or null when unparsable. */
export function originOf(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  let parsed: URL;
  try {
    parsed = new URL(value.trim());
  } catch {
    return null;
  }
  const scheme = parsed.protocol.toLowerCase();
  if (!ALLOWED_SCHEMES.has(scheme)) return null;
  const host = parsed.hostname.toLowerCase();
  if (!host) return null;
  const port = parsed.port === '' ? '' : `:${parsed.port}`;
  return `${scheme}//${host}${port}`;
}

export function isSameOrigin(a: unknown, b: unknown): boolean {
  const left = originOf(a);
  const right = originOf(b);
  return left !== null && right !== null && left === right;
}

/**
 * Navigation gate used by the trusted host for every navigation/redirect.
 * Fail-closed: an unparsable candidate, an out-of-scope origin, or a URL that
 * the policy refuses all produce `false`.
 */
export function isNavigationPermitted(candidate: unknown, approvedUrl: string): boolean {
  if (!isPermittedPublicUrl(candidate)) return false;
  return isSameOrigin(candidate, approvedUrl);
}
