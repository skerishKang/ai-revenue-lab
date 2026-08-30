const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const routes = require('./route-registry.cjs');

const repoRoot = path.resolve(__dirname, '..', '..');

test('B46 route is bounded to the approved current-main AI Personalization Engine runtime', () => {
  const route = routes.find(candidate => candidate.number === 46);
  assert.ok(route, 'missing B46 route');
  assert.equal(route.route, 'b46');
  assert.equal(route.sourcePath, 'reference/business-46-ai-personalization-engine-v1');
  assert.equal(route.mode, 'STATIC_REFERENCE');
  assert.equal(route.marker, 'AI 개인화 엔진');
  assert.deepEqual(route.includeFiles, ['index.html']);
  assert.deepEqual(route.includeDirs, ['assets', 'scripts', 'styles']);

  const source = path.join(repoRoot, route.sourcePath);
  const index = fs.readFileSync(path.join(source, 'index.html'), 'utf8');
  const review = fs.readFileSync(path.join(source, 'scripts', 'review.js'), 'utf8');

  assert.match(index, /AI 개인화 엔진/);
  assert.match(index, /VISUAL REFERENCE ONLY/);
  assert.match(index, /NO TRACKING, AD TARGETING, OR LIVE PERSONALIZATION/);
  assert.match(index, /INFERRED PREFERENCE — NOT USED/);
  assert.match(index, /SENSITIVE INFERENCE PROHIBITED/);
  assert.match(index, /NO AUTOMATIC WINNER/);
  assert.match(index, /MISSING DATA/);
  assert.match(index, /FALLBACK/);
  assert.match(index, /USER OVERRIDE/);
  assert.match(index, /RESET AVAILABLE/);
  assert.doesNotMatch(review, /fetch\s*\(|XMLHttpRequest|WebSocket|EventSource/);

  for (const runtime of ['index.html', 'assets', 'scripts', 'styles']) {
    assert.equal(fs.existsSync(path.join(source, runtime)), true, `B46 source missing runtime ${runtime}`);
  }
  for (const repositoryOnly of [
    'README.md', 'IMAGE_SOURCES.md', 'MOTION_SPEC.md', 'REFERENCE_NOTES.md', 'evidence', 'tests'
  ]) {
    assert.equal(fs.existsSync(path.join(source, repositoryOnly)), true, `B46 source authority missing ${repositoryOnly}`);
    assert.equal(route.includeFiles.includes(repositoryOnly), false, `B46 route directly includes ${repositoryOnly}`);
    assert.equal(route.includeDirs.includes(repositoryOnly), false, `B46 route includes directory ${repositoryOnly}`);
  }
  assert.equal(fs.existsSync(path.join(source, 'ux.html')), false, 'B46 current-main source unexpectedly includes UX #422');
});