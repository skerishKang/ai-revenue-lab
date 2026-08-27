const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B55 route is bounded to the current-main Local AI Fleet static review runtime', () => {
  const route = routes.find(candidate => candidate.number === 55);
  assert.ok(route, 'missing B55 route');
  assert.equal(route.route, 'b55');
  assert.equal(route.sourcePath, 'reference/business-55-local-ai-fleet-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, '로컬 AI 플릿');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /로컬 AI 플릿/);
  assert.match(index, /HUMAN-APPROVED LOCAL MODEL FLEET OPERATIONS PLAN/);
  assert.match(index, /MODEL QUARANTINED/);
  assert.match(index, /WORKER UNAVAILABLE/);
  assert.match(index, /JOB NOT EXECUTED/);
  assert.match(index, /NO AUTOMATIC SCALE-UP/);
  assert.match(index, /FLEET ACTIVATION WITHHELD/);
  assert.match(index, /DUPLICATE JOB PROHIBITED/);
  assert.match(index, /HUMAN RELEASE AUTHORITY/);
  assert.match(index, /BOUNDED RETRY/);
  assert.match(index, /NO LIVE HARDWARE, MODEL DOWNLOAD, INFERENCE, SSH, OR REMOTE CONTROL/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);
});
