// #347 orbit photos on the common login skin: four decorative photos in the
// design order, the design's size/opacity/haze tokens and coordinates, and the
// fourth photo hidden at the narrow width so 390px still shows three.
// The skin stays fixed by the registered client_id: every other product keeps
// the plain PADIEM screen byte for byte.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { AUTH_SKIN_CARD_IMAGES, AUTH_SKIN_CSS } from '../skin.mjs';
import { AUTH_SKIN_ASSETS } from '../skin-assets.mjs';
import { createSkinHarness, EN, normalise, url } from './skin-harness.mjs';

const APP = dirname(fileURLToPath(import.meta.url));
const STATIC = join(APP, '..', 'static', 'auth-skin');
const BASELINE = JSON.parse(readFileSync(join(APP, 'fixtures', 'skin-347-baseline.json'), 'utf8'));

let shared = null;
const setup = async () => (shared ??= await createSkinHarness());

// Values of a single CSS rule, e.g. `:root` or `body.garden`.
function decls(selector) {
  const start = AUTH_SKIN_CSS.indexOf(`${selector}{`);
  assert.ok(start >= 0, `${selector} rule is present`);
  const body = AUTH_SKIN_CSS.slice(start + selector.length + 1, AUTH_SKIN_CSS.indexOf('}', start));
  return Object.fromEntries([...body.matchAll(/(--[a-z0-9-]+):([^;}]+)/g)].map((m) => [m[1], m[2]]));
}

function narrowBlock() {
  const start = AUTH_SKIN_CSS.indexOf('@media (max-width:680px){');
  assert.ok(start >= 0, 'narrow media query is present');
  let depth = 0;
  for (let i = start + '@media (max-width:680px){'.length - 1; i < AUTH_SKIN_CSS.length; i += 1) {
    if (AUTH_SKIN_CSS[i] === '{') depth += 1;
    if (AUTH_SKIN_CSS[i] === '}') { depth -= 1; if (depth === 0) return AUTH_SKIN_CSS.slice(start, i + 1); }
  }
  throw new Error('narrow media query is unbalanced');
}

function orbitImages(html) {
  return [...html.matchAll(/<img class="orbit (o\d)" src="([^"]+)" alt="([^"]*)" width="(\d+)" height="(\d+)">/g)]
    .map((m) => ({ cls: m[1], src: m[2], alt: m[3], width: Number(m[4]), height: Number(m[5]) }));
}

test('the LoveTree screen carries four decorative orbit photos in the design order', async () => {
  const f = await setup();
  const page = await f.begin('/login');
  assert.equal(page.response.status, 200);
  const images = orbitImages(page.html);
  assert.deepEqual(images.map((image) => [image.cls, image.src]), [
    ['o1', '/assets/auth-skin/card-1.webp'],
    ['o2', '/assets/auth-skin/card-3.webp'],
    ['o3', '/assets/auth-skin/card-4.webp'],
    ['o4', '/assets/auth-skin/card-2.webp'],
  ]);
  // Decorative only: empty alt, no accessible name, not focusable.
  for (const image of images) {
    assert.equal(image.alt, '', `${image.cls} stays decorative`);
    assert.equal(image.width, 240);
    assert.equal(image.height, 316);
  }
  assert.ok(!/class="orbit o\d"[^>]*aria-hidden/.test(page.html));
  assert.equal(AUTH_SKIN_CARD_IMAGES.length, 4);
  // The signup screen wears the same four photos.
  const signup = await f.begin('/signup');
  assert.deepEqual(orbitImages(signup.html).map((image) => image.src), images.map((image) => image.src));
});

test('the orbit tokens take the design values for both themes', async () => {
  const night = decls(':root');
  // The seven tokens the request lists, plus the three haze values it asks for.
  assert.deepEqual({
    '--orbit-size': night['--orbit-size'],
    '--orbit-alpha': night['--orbit-alpha'],
    '--orbit-size-small': night['--orbit-size-small'],
    '--orbit-out': night['--orbit-out'],
    '--orbit-card-half': night['--orbit-card-half'],
    '--orbit-gap': night['--orbit-gap'],
  }, {
    '--orbit-size': 'clamp(220px,30vw,420px)',
    '--orbit-alpha': '.8',
    '--orbit-size-small': 'calc(var(--orbit-size) * .72)',
    '--orbit-out': '64px',
    '--orbit-card-half': '220px',
    '--orbit-gap': '48px',
  });
  assert.deepEqual({
    '--orbit-haze-clear': night['--orbit-haze-clear'],
    '--orbit-haze-end': night['--orbit-haze-end'],
    '--orbit-haze-alpha': night['--orbit-haze-alpha'],
  }, { '--orbit-haze-clear': '50%', '--orbit-haze-end': '78%', '--orbit-haze-alpha': '72%' });

  const garden = decls('body.garden');
  assert.equal(garden['--orbit-alpha'], '.7', 'garden keeps the same size, dimmer photos');
  assert.equal(garden['--orbit-size'], undefined, 'garden does not override the size');

  // The rules that consume the tokens, unmodified apart from the token names.
  assert.ok(AUTH_SKIN_CSS.includes('.orbit{position:absolute;z-index:0;height:var(--orbit-size);width:calc(var(--orbit-size) * .76);'));
  assert.ok(AUTH_SKIN_CSS.includes(';opacity:var(--orbit-alpha);pointer-events:none}'));
  assert.ok(AUTH_SKIN_CSS.includes('.o3,.o4{height:var(--orbit-size-small);width:calc(var(--orbit-size-small) * .76)}'));
  assert.ok(!AUTH_SKIN_CSS.includes('clamp(190px,27vw,330px)'), 'the old size is gone');
  assert.ok(!AUTH_SKIN_CSS.includes('opacity:.58'), 'the old opacity is gone');
  assert.ok(!AUTH_SKIN_CSS.includes('opacity:.48'), 'the old garden opacity is gone');
  // The edge haze darkens the stage colour instead of inventing a new one.
  assert.ok(AUTH_SKIN_CSS.includes('color-mix(in srgb,var(--lt-stage) var(--orbit-haze-alpha),transparent) var(--orbit-haze-end)'));
  // The narrow screen keeps its own darker haze, as in the design.
  assert.ok(narrowBlock().includes('.stage::after{background:radial-gradient(ellipse 56% 52% at 50% 46%,transparent 0 42%,var(--lt-stage) 82%)}'));
  // The old single-stop haze only survives as the narrow-screen override.
  assert.ok(!AUTH_SKIN_CSS.replace(narrowBlock(), '').includes('transparent 0 42%,var(--lt-stage) 82%'), 'the old single-stop haze is gone from the wide screen');
});

test('the photos add no motion the reduced-motion setting would have to stop', async () => {
  for (const rule of ['@keyframes', 'animation:', 'transition:', 'will-change', 'scroll-timeline']) {
    assert.ok(!AUTH_SKIN_CSS.includes(rule), rule);
  }
});

test('the four placements copy the design coordinates and rotations', async () => {
  const expected = [
    '.o1{left:calc(50% - var(--orbit-card-half) - var(--orbit-gap) - var(--orbit-size) * .76);top:6%;transform:rotate(-8deg)}',
    '.o2{left:calc(50% + var(--orbit-card-half) + var(--orbit-gap));top:6%;transform:rotate(7deg)}',
    '.o3{left:calc(50% - var(--orbit-card-half) - var(--orbit-gap) - var(--orbit-out) - var(--orbit-size-small) * .76);bottom:5%;transform:rotate(-4deg)}',
    '.o4{left:calc(50% + var(--orbit-card-half) + var(--orbit-gap) + var(--orbit-out));bottom:5%;transform:rotate(4deg)}',
  ];
  for (const rule of expected) assert.ok(AUTH_SKIN_CSS.includes(rule), rule);
  // The old percentage placements and the third-photo-only layout are gone.
  assert.ok(!AUTH_SKIN_CSS.includes('.o1{left:3.5%;top:9%'));
  assert.ok(!AUTH_SKIN_CSS.includes('.o3{right:14%;bottom:5%'));
});

test('390px keeps three photos: the narrow rule hides only the fourth', async () => {
  const block = narrowBlock();
  const hidden = [...block.matchAll(/([^{}]+)\{([^{}]*display:none[^{}]*)\}/g)];
  assert.equal(hidden.length, 1, 'exactly one photo is dropped');
  assert.equal(hidden[0][1], '.o4');
  // 390 < 680, so this block is the one that applies: o1..o3 stay visible.
  assert.ok(block.includes('.orbit{width:128px;height:168px;opacity:.34}'));
  assert.ok(block.includes('.o1{left:-26px;top:6%}'));
  assert.ok(block.includes('.o2{left:auto;right:-28px;top:9%}'), 'o2 must drop the desktop left offset');
  assert.ok(block.includes('.o3{left:auto;right:8%;bottom:2%;width:104px;height:137px}'), 'o3 must drop the desktop left offset');
  assert.ok(!/[^-]\.o[123]\{[^}]*display:none/.test(block));
});

test('the new photo is served from the auth origin with the right type and cache headers', async () => {
  const f = await setup();
  const raw = readFileSync(join(STATIC, 'assets', 'card-4.webp'));
  const response = await f.app.fetch(new Request(`${url}/assets/auth-skin/card-4.webp`));
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('content-type'), 'image/webp');
  assert.ok(response.headers.get('cache-control').includes('max-age=86400'));
  assert.equal(response.headers.get('x-content-type-options'), 'nosniff');
  assert.deepEqual(Buffer.from(await response.arrayBuffer()), raw);
  // WebP container magic, so a renamed PNG cannot pass as the photo.
  assert.equal(raw.subarray(0, 4).toString(), 'RIFF');
  assert.equal(raw.subarray(8, 12).toString(), 'WEBP');
  // The refreshed third photo is the design copy, not the older one.
  const third = readFileSync(join(STATIC, 'assets', 'card-3.webp'));
  const served = await f.app.fetch(new Request(`${url}/assets/auth-skin/card-3.webp`));
  assert.deepEqual(Buffer.from(await served.arrayBuffer()), third);
  assert.equal(AUTH_SKIN_ASSETS['card-4.webp'].type, 'image/webp');
});

test('every other product keeps the plain login screen byte for byte', async () => {
  const f = await setup();
  for (const [key, expected] of Object.entries(BASELINE.plain)) {
    const [path, lang] = key.split('-');
    const page = await f.begin(path, 'brandless', {}, lang === 'en' ? EN : {});
    assert.equal(page.response.status, expected.status, key);
    assert.equal(normalise(page.html), expected.html, `${key} changed`);
    assert.ok(!page.html.includes('orbit'), `${key} must not grow orbit photos`);
    assert.ok(!page.html.includes('--orbit-size'), `${key} must not carry orbit tokens`);
    assert.ok(!page.html.includes('LoveTree'), key);
  }
});

test('the LoveTree login form markup is unchanged by the photo work', async () => {
  const f = await setup();
  for (const [key, expected] of Object.entries(BASELINE.brandForm)) {
    const [path, lang] = key.split('-');
    const page = await f.begin(path, 'lovetree-4-0', {}, lang === 'en' ? EN : {});
    const form = normalise(page.html.match(/<form[^>]*>[\s\S]*?<\/form>/)?.[0] || '');
    assert.equal(form, expected, `${key} form changed`);
  }
  // Garden differs from night in the hidden theme value only.
  for (const path of ['/login', '/signup']) {
    const night = await f.begin(path, 'lovetree-4-0');
    const garden = await f.begin(path, 'lovetree-4-0', { lt_theme: 'garden' });
    const formOf = (page) => normalise(page.html.match(/<form[^>]*>[\s\S]*?<\/form>/)?.[0] || '');
    assert.equal(formOf(garden).replace('value="garden"', 'value="night"'), formOf(night).replace('value="night"', 'value="night"'), path);
  }
  // Field names, the theme carry and the submit button are the same set.
  const page = await f.begin('/login');
  const form = page.html.match(/<form[^>]*>[\s\S]*?<\/form>/)?.[0] || '';
  assert.deepEqual([...form.matchAll(/name="([^"]+)"/g)].map((m) => m[1]), ['lt_theme', 'email', 'password']);
  assert.ok(form.startsWith('<form method="post" action="/login/password?state='));
  assert.ok(form.includes('<button class="btn primary submit" type="submit">이메일로 로그인</button>'));
  assert.ok(page.response.headers.get('set-cookie').includes('HttpOnly'));
});

test('the skin css and the fourth photo never reach a non-LoveTree page', async () => {
  const f = await setup();
  const plain = await f.begin('/login', 'brandless');
  for (const marker of ['AUTH_SKIN', '--lt-pearl', 'Gowun Batang', 'card-4.webp', 'orbit']) {
    assert.ok(!plain.html.includes(marker), marker);
  }
  const skin = await f.begin('/login', 'lovetree-4-0');
  assert.ok(skin.html.includes('--orbit-size:clamp(220px,30vw,420px)'), 'the tokens are inline on the brand page');
});
