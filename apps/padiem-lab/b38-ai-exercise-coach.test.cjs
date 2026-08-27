const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B38 route is bounded to the owner-approved current-main AI Exercise Coach Phase 1 visual reference', () => {
  const route = routes.find(candidate => candidate.number === 38);
  assert.ok(route, 'missing B38 route');
  assert.equal(route.route, 'b38');
  assert.equal(route.sourcePath, 'reference/business-38-ai-exercise-coach-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, 'AI 운동 코치');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /BUSINESS 38 · VISUAL REFERENCE ONLY/);
  assert.match(index, /AI 운동 코치/);
  assert.match(index, /NOT MEDICAL ADVICE/);
  assert.match(index, /NOT A REHABILITATION PLAN/);
  assert.match(index, /NO LIVE CAMERA, BIOMETRIC, OR HEALTH-DATA CONNECTION/);
  assert.match(index, /MOVEMENT OBSERVATION — NOT DIAGNOSIS/);
  assert.match(index, /NO AUTOMATED FORM CERTIFICATION/);
  assert.match(index, /STOP OR PAUSE CONDITION/);
  assert.match(index, /HUMAN-REVIEWED ADAPTIVE MOVEMENT PLAN/);
  assert.match(index, /UNKNOWN \/ NOT ASSESSED/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B38 source missing runtime ${runtime}`);
  }

  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md',
    'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B38 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B38 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B38 route includes directory ${repositoryOnly}`);
  }

  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B38 approved Phase 1 source unexpectedly contains unapproved UX surface');
});
