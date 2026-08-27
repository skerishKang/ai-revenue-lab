const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B42 route is bounded to the owner-approved current-main AI Development Control Tower Phase 1 visual reference', () => {
  const route = routes.find(candidate => candidate.number === 42);
  assert.ok(route, 'missing B42 route');
  assert.equal(route.route, 'b42');
  assert.equal(route.sourcePath, 'reference/business-42-ai-development-control-tower-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, 'AI 개발 관제실');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /AI 개발 관제실/);
  assert.match(index, /VISUAL REFERENCE ONLY/);
  assert.match(index, /SYNTHETIC SOFTWARE PROJECT/);
  assert.match(index, /NO LIVE REPOSITORY, CI, MERGE, OR DEPLOYMENT CONNECTION/);
  assert.match(index, /IMPLEMENTATION REPORT — UNVERIFIED/);
  assert.match(index, /INDEPENDENT EVIDENCE/);
  assert.match(index, /STALE EVIDENCE — DO NOT USE/);
  assert.match(index, /HUMAN REVIEWER/);
  assert.match(index, /UX NOT AUTHORIZED/);
  assert.match(index, /BACKEND FROZEN/);
  assert.match(index, /MERGEABLE ≠ MERGE AUTHORIZED/);
  assert.match(index, /DEPLOYMENT AUTHORIZED — NOT EXECUTED/);
  assert.match(index, /HUMAN-APPROVED DEVELOPMENT CONTROL RECORD/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B42 source missing runtime ${runtime}`);
  }

  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md',
    'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B42 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B42 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B42 route includes directory ${repositoryOnly}`);
  }

  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B42 approved Phase 1 source unexpectedly contains the separately stacked UX surface');
});
