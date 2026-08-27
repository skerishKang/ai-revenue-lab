const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B53 route is bounded to the current-main Embedded AI SDK static review runtime', () => {
  const route = routes.find(candidate => candidate.number === 53);
  assert.ok(route, 'missing B53 route');
  assert.equal(route.route, 'b53');
  assert.equal(route.sourcePath, 'reference/business-53-embedded-ai-sdk-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, '임베드 AI SDK');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /임베드 AI SDK/);
  assert.match(index, /HUMAN-APPROVED EMBEDDED AI INTEGRATION SPEC/);
  assert.match(index, /HOST AUTHORITY/);
  assert.match(index, /SDK INTEGRATION BOUNDARY/);
  assert.match(index, /ACCEPTED INPUT/);
  assert.match(index, /REJECTED INPUT/);
  assert.match(index, /PERMISSION REQUIRED — NOT GRANTED/);
  assert.match(index, /MODEL\/PROVIDER — NOT CONNECTED/);
  assert.match(index, /INSTALLATION NOT PERFORMED/);
  assert.match(index, /EXECUTION NOT PERFORMED/);
  assert.match(index, /FAIL-CLOSED FALLBACK/);
  assert.match(index, /NO HOST MUTATION/);
  assert.match(index, /HUMAN RELEASE AUTHORITY/);
  assert.match(index, /RELEASE WITHHELD/);
  assert.match(index, /NO LIVE HOST, SDK, MODEL, ACCOUNT, OR CREDENTIAL CONNECTION/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);
});
