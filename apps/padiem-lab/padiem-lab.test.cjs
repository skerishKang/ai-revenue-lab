const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const root = __dirname;
const manifest = require('./public-businesses.js');
const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8');
const app = fs.readFileSync(path.join(root, 'app.js'), 'utf8');

const ROUTE_KINDS = new Set(['LOCAL_STATIC', 'EXTERNAL_RUNTIME', 'PRIVATE_PREVIEW', 'NOT_PUBLIC']);
const PUBLIC_STATUSES = new Set(['LIVE', 'PREVIEW', 'BUILDING']);
const FORBIDDEN_KEYS = new Set([
  'issue', 'issueNumber', 'pr', 'prNumber', 'ci', 'checks', 'backendStatus',
  'uiStatus', 'uxStatus', 'workspace', 'exactHead', 'headSha', 'workQueue',
  'githubStatus', 'reviewNotes', 'privateSourcePath'
]);

test('public manifest is curated and has unique Business identities', () => {
  assert.ok(Array.isArray(manifest));
  assert.ok(manifest.length >= 1);
  const numbers = manifest.map(item => item.number);
  assert.equal(new Set(numbers).size, numbers.length);
  for (const item of manifest) {
    assert.equal(Number.isInteger(item.number), true);
    assert.match(item.slug, /^[a-z0-9-]+$/);
    assert.ok(item.title);
    assert.ok(item.koreanTitle);
    assert.ok(item.summary);
    assert.ok(PUBLIC_STATUSES.has(item.publicStatus));
    assert.ok(ROUTE_KINDS.has(item.routeKind));
    assert.match(item.targetPath, /^\/b\d{2}\/$/);
  }
});

test('public manifest exposes no operations-only keys', () => {
  for (const item of manifest) {
    for (const key of Object.keys(item)) {
      assert.equal(FORBIDDEN_KEYS.has(key), false, `forbidden public key: ${key}`);
    }
  }
});

test('external public URLs are HTTPS and private StoryMemory preview is not exposed', () => {
  assert.equal(manifest.some(item => item.number === 61), false);
  for (const item of manifest) {
    if (!item.currentPublicUrl) continue;
    assert.notEqual(item.routeKind, 'LOCAL_STATIC');
    const parsed = new URL(item.currentPublicUrl);
    assert.equal(parsed.protocol, 'https:');
    assert.equal(parsed.hostname.includes('preview.storymemory'), false);
  }
});

test('static Portal routes use curated repository-public sources and no independent public URL', () => {
  const staticItems = manifest.filter(item => item.routeKind === 'LOCAL_STATIC');
  assert.ok(staticItems.length >= 1);
  for (const item of staticItems) {
    assert.match(
      item.sourcePath,
      /^(?:reference\/business-\d{2}-[^/]+|apps\/[a-z0-9-]+\/pages-preview(?:\/site)?)\/$/
    );
    assert.equal(item.targetPath, `/b${String(item.number).padStart(2, '0')}/`);
    assert.equal(item.currentPublicUrl, undefined);
  }
  const b60 = manifest.find(item => item.number === 60);
  assert.equal(b60?.routeKind, 'LOCAL_STATIC');
  assert.equal(b60?.targetPath, '/b60/');
});

test('independent runtime boundaries are preserved for B14 and B62', () => {
  assert.equal(manifest.find(item => item.number === 14)?.routeKind, 'EXTERNAL_RUNTIME');
  assert.equal(manifest.find(item => item.number === 62)?.routeKind, 'EXTERNAL_RUNTIME');
});

test('public shell is indexable and does not load private console runtime', () => {
  assert.doesNotMatch(html, /noindex|nofollow|noarchive/i);
  assert.doesNotMatch(html, /business-manifest\.js|github-live-status\.js|business-live-facts\.js/);
  assert.doesNotMatch(html, /프로젝트 현황|작업 중|백엔드|CI|Pull Request|Issue/);
  assert.match(html, /PADIEM <span>LAB<\/span>/);
  assert.match(html, /public-businesses\.js/);
  assert.match(html, /app\.js/);
});

test('browser renderer prefers validated same-site routes for LOCAL_STATIC and safe HTTPS for external runtime', () => {
  assert.match(app, /PADIEM_LAB_BUSINESSES/);
  assert.match(app, /parsed\.protocol === "https:"/);
  assert.match(app, /\^\\\/b\\d\{2\}\\\/\$/);
  assert.match(app, /item\.routeKind === "LOCAL_STATIC"/);
  assert.match(app, /publicLink\(item\)/);
  assert.match(app, /destination\.external/);
  assert.doesNotMatch(app, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);
  assert.doesNotMatch(app, /api\/github-status|github-live-status/);
});
