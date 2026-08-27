const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B33 route is bounded to the owner-approved current-main Research Memory Phase 1 visual reference', () => {
  const route = routes.find(candidate => candidate.number === 33);
  assert.ok(route, 'missing B33 route');
  assert.equal(route.route, 'b33');
  assert.equal(route.sourcePath, 'reference/business-33-research-memory-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, '연구 기억실');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /BUSINESS 33 · UI_ONLY/);
  assert.match(index, /연구 기억실/);
  assert.match(index, /SYNTHETIC RESEARCH PROJECT/);
  assert.match(index, /VISUAL REFERENCE ONLY/);
  assert.match(index, /NO LIVE SEARCH, INGESTION, OR CITATION AUTHORITY/);
  assert.match(index, /HUMAN-REVIEWED RESEARCH MEMORY/);
  assert.match(index, /fictional/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B33 source missing runtime ${runtime}`);
  }

  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md',
    'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B33 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B33 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B33 route includes directory ${repositoryOnly}`);
  }

  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B33 approved Phase 1 source unexpectedly contains orphaned UX surface');
});
