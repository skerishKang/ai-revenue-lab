const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B47 route is bounded to the approved current-main Real-Time Feedback Engine runtime', () => {
  const route = routes.find(candidate => candidate.number === 47);
  assert.ok(route, 'missing B47 route');
  assert.equal(route.route, 'b47');
  assert.equal(route.sourcePath, 'reference/business-47-real-time-feedback-engine-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, 'Feedback Reaction Room');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /Feedback Reaction Room/);
  assert.match(index, /VISUAL REFERENCE ONLY/);
  assert.match(index, /NO LIVE MONITORING, MODERATION, OR DOWNSTREAM EXECUTION/);
  assert.match(index, /REPRESENTATIVENESS NOT ESTABLISHED/);
  assert.match(index, /NO AUTOMATIC WINNER/);
  assert.match(index, /ACTION AUTHORITY — HUMAN ONLY/);
  assert.match(index, /EXECUTION WITHHELD/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B47 source missing runtime ${runtime}`);
  }
  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md', 'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B47 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B47 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B47 route includes directory ${repositoryOnly}`);
  }
  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B47 current-main source unexpectedly includes UX #423');
});