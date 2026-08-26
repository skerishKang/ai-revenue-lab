const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');
const sourceRoot = path.join(repoRoot, 'reference', 'business-59-living-archive-v1');

test('B59 is a bounded current-main static Portal route', () => {
  const route = routes.find(candidate => candidate.number === 59);
  assert.ok(route, 'B59 route missing');
  assert.equal(route.route, 'b59');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.sourcePath, 'reference/business-59-living-archive-v1');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['scripts', 'styles']);
});

test('B59 authored runtime remains local-only and session-memory-only', () => {
  const index = fs.readFileSync(path.join(sourceRoot, 'index.html'), 'utf8');
  const runtime = fs.readFileSync(path.join(sourceRoot, 'scripts', 'living-archive.js'), 'utf8');
  const fixtures = fs.readFileSync(path.join(sourceRoot, 'scripts', 'fixtures.js'), 'utf8');
  const authored = `${runtime}\n${fixtures}`;

  assert.match(index, /Living Archive/);
  assert.match(index, /Local-first prototype/);
  assert.match(index, /이 MVP는 실제 업로드나 저장을 수행하지 않습니다/);
  assert.match(index, /type="file"/);
  assert.doesNotMatch(index, /<form\b[^>]*method=["']post["']/i);
  assert.doesNotMatch(index, /<form\b[^>]*action=/i);

  assert.doesNotMatch(authored, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource|navigator\.sendBeacon/i);
  assert.doesNotMatch(authored, /localStorage|sessionStorage|indexedDB/i);
  assert.doesNotMatch(authored, /FileReader|readAsArrayBuffer|readAsText|arrayBuffer\s*\(/i);
  assert.match(runtime, /notes:\s*new Map\(\)/);
  assert.match(runtime, /bookmarks:\s*new Set\(\)/);
  assert.match(runtime, /event\.target\.value\s*=\s*["']["']/);
});
