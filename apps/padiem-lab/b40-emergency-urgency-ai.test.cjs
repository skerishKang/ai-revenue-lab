const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B40 route is bounded to the owner-approved current-main Emergency Urgency AI Phase 1 visual reference', () => {
  const route = routes.find(candidate => candidate.number === 40);
  assert.ok(route, 'missing B40 route');
  assert.equal(route.route, 'b40');
  assert.equal(route.sourcePath, 'reference/business-40-emergency-urgency-ai-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, '긴급도 근거 검토 데스크');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /BUSINESS 40 · VISUAL REFERENCE ONLY/);
  assert.match(index, /SYNTHETIC TRAINING INCIDENT/);
  assert.match(index, /SOURCE REPORT — UNVERIFIED/);
  assert.match(index, /CONFLICTING EVIDENCE/);
  assert.match(index, /MISSING INFORMATION/);
  assert.match(index, /UNRESOLVED UNCERTAINTY/);
  assert.match(index, /FINAL PRIORITY AUTHORITY — HUMAN ONLY/);
  assert.match(index, /NO AUTONOMOUS TRIAGE/);
  assert.match(index, /NO MEDICAL DIAGNOSIS/);
  assert.match(index, /NO THREAT PREDICTION/);
  assert.match(index, /NO DISPATCH OR RESOURCE ALLOCATION/);
  assert.match(index, /NO LIVE CALL, LOCATION, SENSOR, OR HEALTH-DATA CONNECTION/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B40 source missing runtime ${runtime}`);
  }

  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md',
    'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B40 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B40 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B40 route includes directory ${repositoryOnly}`);
  }

  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B40 approved fixed Phase 1 source unexpectedly contains unapproved UX surface');
});
