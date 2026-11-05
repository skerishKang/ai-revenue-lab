import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const publicRoot = path.join(appRoot, 'public');
const headersSource = fs.readFileSync(path.join(publicRoot, '_headers'), 'utf8');
const workerSource = fs.readFileSync(path.join(publicRoot, '_worker.js'), 'utf8');

function parseHeaders(source) {
  const rules = [];
  let current = null;
  for (const raw of source.split(/\r?\n/)) {
    if (!raw.trim() || raw.trim().startsWith('#')) continue;
    if (!/^\s/.test(raw)) {
      current = { pattern: raw.trim(), headers: {} };
      rules.push(current);
      continue;
    }
    const match = raw.trim().match(/^([^:]+):\s*(.+)$/);
    if (match && current) current.headers[match[1].toLowerCase()] = match[2].trim();
  }
  return rules;
}

function matches(pattern, pathname) {
  const star = pattern.indexOf('*');
  if (star < 0) return pattern === pathname;
  const prefix = pattern.slice(0, star);
  const suffix = pattern.slice(star + 1);
  return pathname.startsWith(prefix) && pathname.endsWith(suffix);
}

function cacheControlFor(pathname, rules = parseHeaders(headersSource)) {
  const rule = rules.find((candidate) => matches(candidate.pattern, pathname));
  return rule?.headers['cache-control'] ?? null;
}

const LONG = 'public, max-age=604800, stale-while-revalidate=2592000';
const SHELL = 'public, max-age=86400, stale-while-revalidate=604800';

test('_headers applies the required cache policy per path', () => {
  const cases = [
    ['/content/bible-web/search-index/manifest.json', LONG],
    ['/content/bible-web/search-index/shard-01.json', LONG],
    ['/content/bible-web/book-GEN-chapter-001.json', LONG],
    ['/styles/storymemory-review-261031.css', SHELL],
    ['/bookai-bootstrap.js', SHELL],
    ['/storymemory-source-ui.css', SHELL],
    ['/app-ai-transport.mjs', SHELL],
    ['/', 'no-cache'],
    ['/index.html', 'no-cache'],
    ['/version.json', 'no-cache'],
    ['/api/storymemory-ai/health', 'no-cache'],
    ['/api/bookai/records', 'no-cache'],
  ];
  for (const [pathname, expected] of cases) {
    assert.equal(cacheControlFor(pathname), expected, pathname);
  }
});

test('the worker applies the same policy to env.ASSETS responses', () => {
  assert.match(workerSource, /function assetCacheControl\(pathname\)/);
  assert.match(workerSource, /await env\.ASSETS\.fetch\(request\)/);
  assert.match(workerSource, /return serveAsset\(request, env\);/);
  assert.ok(!/return env\.ASSETS\.fetch\(request\);/.test(workerSource), 'asset fallback must use serveAsset');
  for (const value of [LONG, SHELL, 'no-cache']) {
    assert.ok(workerSource.includes(value), value);
  }
  assert.ok(workerSource.includes('"cache-control": "no-store"'), 'API json responses stay no-store');
});
