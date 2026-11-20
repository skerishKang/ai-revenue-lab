// #8175 — 이메일을 러브트리 전용 서비스 서명으로 묶는다.
// 응답 본문에만 실리고, 로그·주소·오류에는 이메일을 넣지 않는다.
export const EMAIL_ASSERTION_CLIENT = 'lovetree-4-0';
export const EMAIL_ASSERTION_AUDIENCE = 'lovetree';
export const EMAIL_ASSERTION_TTL = 600;

const encoder = new TextEncoder();
const decoder = new TextDecoder('utf-8', { fatal: true });
const b64url = (bytes) => btoa(String.fromCharCode(...bytes))
  .replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
const unb64url = (text) => Uint8Array.from(
  atob(text.replaceAll('-', '+').replaceAll('_', '/').padEnd(Math.ceil(text.length / 4) * 4, '=')),
  (ch) => ch.charCodeAt(0));

async function hmac(secret, text) {
  if (typeof secret !== 'string' || !secret) throw new Error('assertion key unavailable');
  const key = await crypto.subtle.importKey('raw', encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return new Uint8Array(await crypto.subtle.sign('HMAC', key, encoder.encode(text)));
}

function equal(a, b) {
  if (a.length !== b.length) return false;
  let difference = 0;
  for (let i = 0; i < a.length; i += 1) difference |= a[i] ^ b[i];
  return difference === 0;
}

/** 토큰 교환 응답에 넣을 필드. 비밀·클라이언트·이메일 중 하나라도 없으면 빈 객체. */
export async function emailAssertionField({ clientId, secret, profile, sub, now }) {
  if (clientId !== EMAIL_ASSERTION_CLIENT || !secret || !profile ||
      typeof profile.email !== 'string' || !profile.email.trim()) return {};
  if (typeof sub !== 'string' || !sub || !Number.isInteger(now)) return {};
  const email = profile.email.trim().toLowerCase();
  const payload = b64url(encoder.encode(JSON.stringify({
    sub, email, email_verified: profile.email_verified === true,
    aud: EMAIL_ASSERTION_AUDIENCE, iat: now, exp: now + EMAIL_ASSERTION_TTL,
  })));
  const signature = b64url(await hmac(secret, 'v1.' + payload));
  return { email_assertion: 'v1.' + payload + '.' + signature };
}

/** 수신 측 검증 — 성공하면 payload, 아니면 null. 시각은 주입한다. */
export async function verifyEmailAssertion({ assertion, secret, now, aud = EMAIL_ASSERTION_AUDIENCE }) {
  try {
    if (typeof assertion !== 'string') return null;
    const parts = assertion.split('.');
    if (parts.length !== 3 || parts[0] !== 'v1' || !parts[1] || !parts[2]) return null;
    const expected = await hmac(secret, 'v1.' + parts[1]);
    if (!equal(unb64url(parts[2]), expected)) return null;
    const claim = JSON.parse(decoder.decode(unb64url(parts[1])));
    if (!claim || typeof claim !== 'object' || claim.aud !== aud ||
        typeof claim.sub !== 'string' || !claim.sub ||
        typeof claim.email !== 'string' || !claim.email ||
        typeof claim.email_verified !== 'boolean' ||
        !Number.isInteger(claim.iat) || !Number.isInteger(claim.exp) ||
        claim.exp !== claim.iat + EMAIL_ASSERTION_TTL ||
        !Number.isInteger(now) || now < claim.iat || now >= claim.exp) return null;
    return claim;
  } catch {
    return null;
  }
}
