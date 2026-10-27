import test from 'node:test';
import assert from 'node:assert/strict';
import { createPublicSupplyConsumerHttpHandler } from '../src/http/consumer-http.js';
import {
  THEME_COOKIE_NAME,
  readThemeFromCookie,
  themeCookieHeaderValue,
  themeToggleHref,
} from '../src/ui/theme.js';

const handler = createPublicSupplyConsumerHttpHandler();

const ALL_ROUTES = ['/', '/today', '/browse', '/detail?id=none', '/pipeline', '/income'] as const;

function cookieValueOf(response: Response, name: string): string | null {
  const raw = response.headers.get('set-cookie');
  if (!raw) return null;
  for (const part of raw.split(/,(?=[^;]+=)/)) {
    if (part.trim().startsWith(`${name}=`)) return part.trim();
  }
  return null;
}

test('first visit defaults to Light on every consumer route', async () => {
  for (const route of ALL_ROUTES) {
    const res = await handler(new Request(`https://b64.example${route}`));
    assert.ok(res.status === 200 || res.status === 404, `${route}: unexpected status ${res.status}`);
    const html = await res.text();
    assert.match(html, /<html lang="ko" data-theme="light">/, route);
    assert.match(html, /<meta name="color-scheme" content="light" \/>/, route);
    assert.match(html, /class="theme-toggle"/, `toggle present on ${route}`);
    assert.match(html, /aria-label="다크 테마로 전환"/, route);
    assert.match(html, /:root \{\s*color-scheme: light;/, `light variables on ${route}`);
    assert.match(html, /html\[data-theme="dark"\] \{/, `dark override shipped on ${route}`);
    assert.ok(!/:root \{\s*color-scheme: dark/.test(html), 'dark is no longer the :root default');
  }
  // The detail 404 (unknown opportunity) is themed as well.
  const detail404 = await handler(new Request('https://b64.example/detail?id=none'));
  assert.equal(detail404.status, 404);
  assert.match(await detail404.text(), /data-theme="light">/);
});

test('the persisted dark choice re-renders every route in dark', async () => {
  for (const route of ALL_ROUTES) {
    const res = await handler(new Request(`https://b64.example${route}`, {
      headers: { cookie: `${THEME_COOKIE_NAME}=dark` },
    }));
    const html = await res.text();
    assert.match(html, /<html lang="ko" data-theme="dark">/, route);
    assert.match(html, /<meta name="color-scheme" content="dark" \/>/, route);
    assert.match(html, /aria-label="라이트 테마로 전환"/, `toggle announces the switch back on ${route}`);
  }
});

test('an invalid or tampered cookie value falls back to Light', async () => {
  for (const value of ['blue', '', 'LIGHT', 'dark dark']) {
    const res = await handler(new Request('https://b64.example/', {
      headers: { cookie: `${THEME_COOKIE_NAME}=${value}` },
    }));
    const html = await res.text();
    assert.match(html, /data-theme="light">/, `value ${JSON.stringify(value)} must not authenticate a dark theme`);
  }
  assert.equal(readThemeFromCookie(null), 'light');
  assert.equal(readThemeFromCookie('other=1'), 'light');
});

test('the toggle link flips the theme cookie and returns to the same route', async () => {
  const res = await handler(new Request('https://b64.example/?theme=toggle'));
  assert.equal(res.status, 303);
  assert.equal(res.headers.get('location'), '/');
  const setCookie = cookieValueOf(res, THEME_COOKIE_NAME);
  assert.ok(setCookie);
  assert.match(setCookie, /^b64_theme=dark;/);
  assert.match(setCookie, /HttpOnly/);
  assert.match(setCookie, /SameSite=Lax/);
  assert.match(setCookie, /Secure/);
  assert.match(setCookie, /Max-Age=\d+/);

  // The stored choice survives navigation: reuse the cookie on another route.
  const cookie = setCookie!.split(';')[0]!;
  const next = await handler(new Request('https://b64.example/today', { headers: { cookie } }));
  assert.match(await next.text(), /data-theme="dark">/);
});

test('toggling from dark goes back to Light and keeps route filters', async () => {
  const res = await handler(new Request('https://b64.example/browse?category=ALL&q=test&theme=toggle', {
    headers: { cookie: `${THEME_COOKIE_NAME}=dark` },
  }));
  assert.equal(res.status, 303);
  assert.equal(res.headers.get('location'), '/browse?category=ALL&q=test');
  const setCookie = cookieValueOf(res, THEME_COOKIE_NAME);
  assert.match(setCookie!, /^b64_theme=light;/);

  // The toggle link rendered on a filtered browse page keeps the filters.
  const page = await handler(new Request('https://b64.example/browse?category=ALL&q=test'));
  const html = await page.text();
  assert.match(html, /href="\/browse\?category=ALL&amp;q=test&amp;theme=toggle"/);
});

test('theme toggle requests never accept POST', async () => {
  const res = await handler(new Request('https://b64.example/?theme=toggle', { method: 'POST' }));
  assert.equal(res.status, 405);
});

test('toggle hrefs are HTML-escaped and stay same-origin', async () => {
  const res = await handler(new Request('https://b64.example/browse?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E'));
  const html = await res.text();
  assert.ok(!html.includes('<script>alert(1)</script>"'), 'raw query must not be injected into the toggle href');
  // URLSearchParams re-encodes the value; the href must stay percent-encoded
  // (and therefore inert) inside the attribute.
  assert.match(html, /href="\/browse\?q=%3Cscript%3Ealert%281%29%3C%2Fscript%3E&amp;theme=toggle"/);
});

test('the theme feature leaves the CSP and security headers untouched', async () => {
  const res = await handler(new Request('https://b64.example/'));
  assert.equal(
    res.headers.get('content-security-policy'),
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
  );
  const toggle = await handler(new Request('https://b64.example/?theme=toggle'));
  assert.equal(
    toggle.headers.get('content-security-policy'),
    "default-src 'none'; style-src 'unsafe-inline'; script-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
  );
  assert.equal(toggle.headers.get('x-frame-options'), 'DENY');
  const html = await (await handler(new Request('https://b64.example/'))).text();
  assert.ok(!/<script/i.test(html), 'no script element may be introduced by theming');
});

test('pipeline POST contracts are unaffected by the theme layer', async () => {
  const noAuth = await handler(new Request('https://b64.example/pipeline', {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: 'action=save&title=Theme&vendor=V&status=SAVED',
  }));
  assert.equal(noAuth.status, 401);
});

test('shared helpers keep the toggle link target per-route', () => {
  assert.equal(themeToggleHref('/today', new URLSearchParams()), '/today?theme=toggle');
  assert.equal(themeToggleHref('/income', new URLSearchParams('status=PAID')), '/income?status=PAID&theme=toggle');
  assert.equal(themeCookieHeaderValue('light'), 'b64_theme=light; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax; Secure');
});

test('existing dark design values are preserved for the dark override', async () => {
  const res = await handler(new Request('https://b64.example/', { headers: { cookie: `${THEME_COOKIE_NAME}=dark` } }));
  const html = await res.text();
  assert.match(html, /--bg: #06080d;/, 'the original dark background stays');
  assert.match(html, /--accent: #88c9ff;/, 'the original dark accent palette is preserved');
  assert.match(html, /--gold: #efc984;/, 'the original dark gold stays');
  assert.match(html, /--on-accent: #06080d;/, 'dark buttons keep dark-on-accent text');
});
